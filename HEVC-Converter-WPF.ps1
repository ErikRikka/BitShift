# Конвертер HEVC — WPF-версия (тёмный интерфейс: скруглённые карточки, тени, пилюли).
# Логика конвейера та же, что в WinForms-версии: кодеки AV1/HEVC/DNxHR, _v2 в именах,
# SSD-кэш для USB-дисков, совмещённая проверка с кодированием, все гарантии.
# Запуск без консоли: «Конвертер HEVC.exe» или «Конвертер HEVC GUI.vbs».
# Тест без окна: $env:HEVC_WPF_TEST='1' + дот-сорсинг; staged-тест: HEVC_WPF_FORCESTAGE='1'.
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Windows.Forms, System.Xaml

# строка списка файлов (INotifyPropertyChanged -> список сам обновляется при смене статуса)
if (-not ('FileRow' -as [type])) {
Add-Type -ReferencedAssemblies PresentationCore, WindowsBase, System.Xaml -TypeDefinition @'
using System.ComponentModel;
using System.Windows.Media;
public class FileRow : INotifyPropertyChanged {
  public event PropertyChangedEventHandler PropertyChanged;
  void N(string p){ var h=PropertyChanged; if(h!=null) h(this, new PropertyChangedEventArgs(p)); }
  public string Name { get; set; }
  public string Size { get; set; }
  public bool   CanCheck { get; set; }
  public object Tag { get; set; }
  string _info=""; public string Info { get{return _info;} set{_info=value; N("Info");} }
  string _status=""; public string Status { get{return _status;} set{_status=value; N("Status");} }
  Brush _sc; public Brush StatusColor { get{return _sc;} set{_sc=value; N("StatusColor");} }
  bool _chk; public bool IsChecked { get{return _chk;} set{_chk=value; N("IsChecked");} }
  // мини-шкала прогресса в строке: ширина заливки в пикселях + цвет текущего этапа
  double _bw; public double BarWidth { get{return _bw;} set{_bw=value; N("BarWidth");} }
  Brush _bc; public Brush BarColor { get{return _bc;} set{_bc=value; N("BarColor");} }
}
'@
}

# выбор НЕСКОЛЬКИХ папок сразу (Ctrl/Shift): системный IFileOpenDialog с флагами
# FOS_PICKFOLDERS + FOS_ALLOWMULTISELECT. Обычный FolderBrowserDialog так не умеет.
try {
  Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class MultiFolderPicker {
  [ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")] private class FileOpenDialogRCW { }

  [ComImport, Guid("d57c7288-d4ad-4768-be02-9d969532d960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  private interface IFileOpenDialog {
    [PreserveSig] int Show(IntPtr parent);
    void SetFileTypes(uint c, IntPtr rg);
    void SetFileTypeIndex(uint i);
    void GetFileTypeIndex(out uint pi);
    void Advise(IntPtr pfde, out uint c);
    void Unadvise(uint c);
    void SetOptions(uint fos);
    void GetOptions(out uint pfos);
    void SetDefaultFolder(IShellItem psi);
    void SetFolder(IShellItem psi);
    void GetFolder(out IShellItem ppsi);
    void GetCurrentSelection(out IShellItem ppsi);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string n);
    void GetFileName(out IntPtr n);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string t);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string t);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string t);
    void GetResult(out IShellItem ppsi);
    void AddPlace(IShellItem psi, int fdap);
    void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string e);
    void Close(int hr);
    void SetClientGuid(ref Guid g);
    void ClearClientData();
    void SetFilter(IntPtr f);
    void GetResults(out IShellItemArray ppenum);
    void GetSelectedItems(out IShellItemArray ppsai);
  }

  [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  private interface IShellItem {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetParent(out IShellItem ppsi);
    void GetDisplayName(uint sigdn, out IntPtr ppsz);
    void GetAttributes(uint mask, out uint attribs);
    void Compare(IShellItem psi, uint hint, out int order);
  }

  [ComImport, Guid("b63ea76d-1f85-456f-a19c-48159efa858b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  private interface IShellItemArray {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetPropertyStore(int flags, ref Guid riid, out IntPtr ppv);
    void GetPropertyDescriptionList(IntPtr key, ref Guid riid, out IntPtr ppv);
    void GetAttributes(int flags, uint mask, out uint attribs);
    void GetCount(out uint n);
    void GetItemAt(uint i, out IShellItem ppsi);
    void EnumItems(out IntPtr ppenum);
  }

  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  private static extern void SHCreateItemFromParsingName(
    [MarshalAs(UnmanagedType.LPWStr)] string path, IntPtr pbc, ref Guid riid,
    [MarshalAs(UnmanagedType.Interface)] out IShellItem ppv);

  private const uint FOS_PICKFOLDERS = 0x20, FOS_FORCEFILESYSTEM = 0x40, FOS_ALLOWMULTISELECT = 0x200;
  private const uint SIGDN_FILESYSPATH = 0x80058000;

  public static string[] Pick(string title, string initial) {
    IFileOpenDialog dlg = (IFileOpenDialog)(new FileOpenDialogRCW());
    uint opts; dlg.GetOptions(out opts);
    dlg.SetOptions(opts | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_ALLOWMULTISELECT);
    if (!string.IsNullOrEmpty(title)) dlg.SetTitle(title);
    if (!string.IsNullOrEmpty(initial) && System.IO.Directory.Exists(initial)) {
      try {
        Guid ig = typeof(IShellItem).GUID; IShellItem si;
        SHCreateItemFromParsingName(initial, IntPtr.Zero, ref ig, out si);
        if (si != null) dlg.SetFolder(si);
      } catch { }
    }
    if (dlg.Show(IntPtr.Zero) != 0) return new string[0];   // отмена
    IShellItemArray arr; dlg.GetResults(out arr);
    uint n; arr.GetCount(out n);
    List<string> res = new List<string>();
    for (uint i = 0; i < n; i++) {
      IShellItem it; arr.GetItemAt(i, out it);
      IntPtr p; it.GetDisplayName(SIGDN_FILESYSPATH, out p);
      if (p != IntPtr.Zero) { res.Add(Marshal.PtrToStringUni(p)); Marshal.FreeCoTaskMem(p); }
    }
    return res.ToArray();
  }
}
'@
} catch { }

# скругление углов окна (DWM, Win11)
try {
  Add-Type -Namespace HevcWpf -Name Dwm -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("dwmapi.dll")] public static extern int DwmSetWindowAttribute(System.IntPtr h, int a, ref int v, int s);
'@
} catch {}

function Br([string]$hex) { $b = New-Object System.Windows.Media.SolidColorBrush ([System.Windows.Media.ColorConverter]::ConvertFromString($hex)); $b.Freeze(); return $b }
$ClrTx = Br '#F0F0F3'; $ClrTx2 = Br '#97979F'; $ClrGray = $ClrTx2
$ClrGreen = Br '#5FCE9A'; $ClrBlue = Br '#7FB2EE'; $ClrRed = Br '#E8756F'
$ClrViolet = Br '#A99BF0'          # этап проверки
$ROWBAR_W = 300.0                  # ширина шкалы в строке (см. Width у Border в шаблоне)

# ---------------- локализация ----------------
# Интерфейс на двух языках. Язык берётся из системы (русская Windows -> русский,
# остальные -> английский), пользователь может переключить вручную.
# Комментарии, лог-файл и техзаметки остаются на русском — это рабочая кухня.
$script:Str = @{
 ru = @{
  sec_mode='РЕЖИМ'; sec_codec='КОДЕК'; sec_audio='ЗВУК'; sec_volume='ОБЪЁМ'; sec_left='ОСТАЛОСЬ'
  mode_old='Старое видео'; mode_cam='Съёмка с камеры'; mode_arc='Обычное видео'
  mode_old_full='Старое видео (AVI, WMV, MTS)'; mode_cam_full='Съёмка с камеры (Log/RAW)'; mode_arc_full='Обычное видео'
  mode_old_tip='Файлы AVI, WMV, MTS — старые камеры и видеокассеты. Результат в MP4.'
  mode_cam_tip="MP4/MOV прямо с камеры (Log, S-Log3, плоская картинка).`nСжимает бережнее: сохраняет 10 бит и цвет для дальнейшей обработки."
  mode_arc_tip="MP4/MOV: смонтированные ролики, съёмки с телефона, архив.`nМаксимальная экономия места. Уже компактные файлы пропускаются."
  codec_av1='AV1  ·  макс. сжатие'; codec_hevc='HEVC  ·  рекомендуется'; codec_dnxhr='DNxHR HQX  ·  грейдинг'
  audio_orig='Оригинал  ·  все каналы'; audio_aac='AAC стерео  ·  компактно'
  btn_browse='Обзор…'; btn_refresh='Обновить'; btn_start='Старт'; btn_pause='Пауза'; btn_resume='Продолжить'; btn_stop='Стоп'
  btn_delete='Удалить проверенные в Корзину…'; btn_delete_n='Удалить проверенные ({0}) в Корзину…'
  chk_sub='Включая подпапки'; chk_shutdown='Выключить компьютер после завершения'
  chk_auto='Удалять исходники в Корзину после проверки'
  hint_safety='Оригиналы не перезаписываются. Удаление — только в Корзину, после проверки.'
  lbl_to_process='К обработке: '; lbl_src_total='Объём исходников: '
  lbl_saved='Сэкономлено: {0} · −{1}%'; lbl_saved_none='Сэкономлено: —'
  lbl_forecast='Прогноз: ~{0} · −{1}%'; lbl_forecast_calc='Прогноз: считаю… {0}/{1}'; lbl_forecast_na='Прогноз: недоступен'
  dev_cpu='Кодирует процессор'; dev_gpu_tip='Кодирует видеокарта {0} (NVENC)'
  dev_cpu_tip='{0} кодируется процессором — видеокарта этот кодек не умеет'
  st_queued='в очереди'; st_encoding='кодирую {0}%'; st_encoding_start='кодирую… ({0} -> {1} кбит/с)'
  st_verifying='проверяю {0}%'; st_verify_wait='проверяю…'; st_done='готово'
  st_verified='проверен — оригинал можно удалять'; st_verified_moved='готово, проверен — оригинал можно удалять'
  st_verified_wait_move='проверен — жду переноса с SSD'; st_moving='переношу результат…'
  st_in_trash='оригинал в Корзине'; st_not_deleted='НЕ удалился'; st_stopped='остановлено'
  st_unchecked='снята галочка — пропущен'; st_ready_pair='уже готов — на проверку'
  st_collision='коллизия имён — пропущен'; st_copying='копирую на SSD…'; st_on_ssd='на SSD, жду слот кодирования'
  st_fast_disk='на быстром диске — кодирую на месте'; st_low_space='мало места на SSD — кодирую напрямую'
  st_hw_retry='hw-декодер не справился — повтор на CPU'; st_audio_retry='звук не скопировался — повтор с AAC'
  st_gone='файл исчез'; st_error='ОШИБКА: '; st_fail='ПРОВАЛ проверки: {0} — оригинал оставлен'
  st_copy_fail='ошибка копирования на SSD (robocopy {0})'; st_move_fail='НЕ смог перенести результат с SSD (robocopy {0})'
  skip_hevc='пропуск: уже HEVC'; skip_compact='пропуск: уже компактный'; skip_gain='пропуск: выигрыш < 10%'
  ready_hevc='уже HEVC — пропуск'; ready_compact='уже компактный — пропуск'
  bad_nofile='файла нет'; bad_codec='результат не тот кодек ({0})'; bad_noduration='нет длительности'
  bad_duration='длительность не совпала'; bad_frames='кадры: {0} vs {1}'; bad_decode='ошибки декодирования'
  run_paused='⏸ ПАУЗА'; run_encoding='кодирование {0}/{1} (в работе {2})'; run_verified='проверено {0}{1}'
  run_failed='провал {0}'; run_moving='перенос результатов…'
  list_summary='{0} новых, {1} уже готово. Сними галочки с ненужных.'
  count_line='{0} файлов{1} · кодек {2}'; folders_note=' · папок {0}'; folders_multi='Папок: {0} — {1}'
  finish='Готово. Сконвертировано {0}, пропущено {1}, ошибок {2}. Проверено целых {3} из {4}.'
  stopped_hint='Остановлено. Готовые пары можно проверить, нажав Старт ещё раз.'
  trash_result='В Корзину: {0}, проблем: {1}.'
  dlg_nofiles='Нет ни выбранных файлов, ни готовых пар для проверки.'
  dlg_confirm="Проверка пройдена: {0} файлов.`n`nУдалить {0} проверенных оригиналов в Корзину?`nИз Корзины всё можно вернуть."
  dlg_closing='Идёт работа. Прервать и выйти?'
  dlg_browse='Папка с видео (можно с подпапками)'; dlg_browse_multi='Папки с видео — можно выбрать несколько (Ctrl)'
  fail_ffmpeg="ffmpeg не найден. Установи его командой:`n`n    winget install Gyan.FFmpeg`n`nи запусти конвертер заново."
  fail_nvenc="В этой сборке ffmpeg нет hevc_nvenc.`nПоставь стандартную сборку: winget install Gyan.FFmpeg"
  shutdown_note='Компьютер выключится через {0} с. Отмена: shutdown /a'
  shutdown_reason='Конвертация завершена — выключение'
  t_lessmin='меньше минуты'; t_min='~{0} мин'; t_hour='~{0} ч'; t_hourmin='~{0} ч {1} мин'; t_day='~{0} дн {1} ч'
  t_calc='считаю…'; t_finishing='завершаем…'
  sz_gb='{0:N1} ГБ'; sz_mb='{0:N0} МБ'; sz_kb='{0:N0} КБ'
  gpu_unknown='видеокарта'; err_none='без сообщения'
  settings='НАСТРОЙКИ'; lang_label='Язык'; gear_tip='Настройки'
 }
 en = @{
  sec_mode='MODE'; sec_codec='CODEC'; sec_audio='AUDIO'; sec_volume='SIZE'; sec_left='REMAINING'
  mode_old='Old video'; mode_cam='Camera footage'; mode_arc='Regular video'
  mode_old_full='Old video (AVI, WMV, MTS)'; mode_cam_full='Camera footage (Log/RAW)'; mode_arc_full='Regular video'
  mode_old_tip='AVI, WMV and MTS files — old camcorders and tapes. Output is MP4.'
  mode_cam_tip="MP4/MOV straight off the camera (Log, S-Log3, flat picture).`nCompresses gently: keeps 10-bit and colour for grading."
  mode_arc_tip="MP4/MOV: edited videos, phone footage, archive.`nMaximum space savings. Already-compact files are skipped."
  codec_av1='AV1  ·  smallest files'; codec_hevc='HEVC  ·  recommended'; codec_dnxhr='DNxHR HQX  ·  grading'
  audio_orig='Original  ·  all channels'; audio_aac='AAC stereo  ·  compact'
  btn_browse='Browse…'; btn_refresh='Refresh'; btn_start='Start'; btn_pause='Pause'; btn_resume='Resume'; btn_stop='Stop'
  btn_delete='Move verified originals to Recycle Bin…'; btn_delete_n='Move verified originals ({0}) to Recycle Bin…'
  chk_sub='Include subfolders'; chk_shutdown='Shut down the computer when finished'
  chk_auto='Move originals to Recycle Bin after verification'
  hint_safety='Originals are never overwritten. Deletion goes to the Recycle Bin only, after verification.'
  lbl_to_process='To process: '; lbl_src_total='Source size: '
  lbl_saved='Saved: {0} · −{1}%'; lbl_saved_none='Saved: —'
  lbl_forecast='Estimate: ~{0} · −{1}%'; lbl_forecast_calc='Estimate: calculating… {0}/{1}'; lbl_forecast_na='Estimate: not available'
  dev_cpu='Encoding on CPU'; dev_gpu_tip='Encoded by {0} (NVENC)'
  dev_cpu_tip='{0} is encoded on the CPU — the GPU does not support this codec'
  st_queued='queued'; st_encoding='encoding {0}%'; st_encoding_start='encoding… ({0} -> {1} kbit/s)'
  st_verifying='verifying {0}%'; st_verify_wait='verifying…'; st_done='done'
  st_verified='verified — original can be removed'; st_verified_moved='done and verified — original can be removed'
  st_verified_wait_move='verified — waiting to move from SSD'; st_moving='moving result…'
  st_in_trash='original in Recycle Bin'; st_not_deleted='could not delete'; st_stopped='stopped'
  st_unchecked='unchecked — skipped'; st_ready_pair='already encoded — will verify'
  st_collision='name collision — skipped'; st_copying='copying to SSD…'; st_on_ssd='on SSD, waiting for a slot'
  st_fast_disk='already on a fast disk — encoding in place'; st_low_space='not enough SSD space — encoding in place'
  st_hw_retry='hardware decoder failed — retrying on CPU'; st_audio_retry='audio could not be copied — retrying with AAC'
  st_gone='file is gone'; st_error='ERROR: '; st_fail='VERIFICATION FAILED: {0} — original kept'
  st_copy_fail='failed to copy to SSD (robocopy {0})'; st_move_fail='could not move result from SSD (robocopy {0})'
  skip_hevc='skipped: already HEVC'; skip_compact='skipped: already compact'; skip_gain='skipped: gain below 10%'
  ready_hevc='already HEVC — skipped'; ready_compact='already compact — skipped'
  bad_nofile='file missing'; bad_codec='wrong codec in result ({0})'; bad_noduration='no duration'
  bad_duration='duration mismatch'; bad_frames='frames: {0} vs {1}'; bad_decode='decoding errors'
  run_paused='⏸ PAUSED'; run_encoding='encoding {0}/{1} ({2} running)'; run_verified='verified {0}{1}'
  run_failed='failed {0}'; run_moving='moving results…'
  list_summary='{0} new, {1} already done. Untick what you do not need.'
  count_line='{0} files{1} · codec {2}'; folders_note=' · {0} folders'; folders_multi='Folders: {0} — {1}'
  finish='Finished. Converted {0}, skipped {1}, errors {2}. Verified intact {3} of {4}.'
  stopped_hint='Stopped. Finished pairs can be verified by pressing Start again.'
  trash_result='Moved to Recycle Bin: {0}, problems: {1}.'
  dlg_nofiles='Nothing to do: no files selected and no finished pairs to verify.'
  dlg_confirm="Verification passed: {0} files.`n`nMove {0} verified originals to the Recycle Bin?`nEverything can be restored from there."
  dlg_closing='A run is in progress. Abort and quit?'
  dlg_browse='Folder with video (subfolders optional)'; dlg_browse_multi='Folders with video — you can pick several (Ctrl)'
  fail_ffmpeg="ffmpeg not found. Install it with:`n`n    winget install Gyan.FFmpeg`n`nthen start BitShift again."
  fail_nvenc="This ffmpeg build has no hevc_nvenc.`nInstall a standard build: winget install Gyan.FFmpeg"
  shutdown_note='The computer will shut down in {0} s. Cancel with: shutdown /a'
  shutdown_reason='Conversion finished — shutting down'
  t_lessmin='less than a minute'; t_min='~{0} min'; t_hour='~{0} h'; t_hourmin='~{0} h {1} min'; t_day='~{0} d {1} h'
  t_calc='calculating…'; t_finishing='finishing…'
  sz_gb='{0:N1} GB'; sz_mb='{0:N0} MB'; sz_kb='{0:N0} KB'
  gpu_unknown='graphics card'; err_none='no message'
  settings='SETTINGS'; lang_label='Language'; gear_tip='Settings'
 }
}
# язык системы: русская Windows -> русский, остальные -> английский
# выбор языка запоминается между запусками: у пользователя может быть английская
# система при русском интерфейсе (и наоборот)
$script:LangFile = Join-Path $env:LOCALAPPDATA 'BitShift-lang.txt'
function Detect-Lang {
  try {
    if (Test-Path -LiteralPath $script:LangFile) {
      $s = (Get-Content -LiteralPath $script:LangFile -TotalCount 1 -ErrorAction Stop).Trim().ToLower()
      if ($s -eq 'ru' -or $s -eq 'en') { return $s }
    }
  } catch {}
  try {
    $c = [System.Globalization.CultureInfo]::CurrentUICulture.TwoLetterISOLanguageName
    if ($c -eq 'ru') { return 'ru' }
  } catch {}
  return 'en'
}
function Save-Lang {
  try { Set-Content -LiteralPath $script:LangFile -Value $script:Lang -Encoding ASCII -ErrorAction Stop } catch {}
}
$script:Lang = Detect-Lang
# разделители чисел должны соответствовать языку интерфейса: 4.9 GB против 4,9 ГБ.
# Разбор данных ffprobe идёт через InvariantCulture, так что это безопасно.
function Apply-Culture {
  try {
    $name = 'en-US'; if ($script:Lang -eq 'ru') { $name = 'ru-RU' }
    [System.Threading.Thread]::CurrentThread.CurrentCulture = [System.Globalization.CultureInfo]::GetCultureInfo($name)
  } catch {}
}
Apply-Culture
function T([string]$k) {
  $d = $script:Str[$script:Lang]
  if ($d -and $d.ContainsKey($k)) { return [string]$d[$k] }
  $e = $script:Str['en']
  if ($e -and $e.ContainsKey($k)) { return [string]$e[$k] }
  return $k
}

function HumanSize([long]$b) {
  if ($b -ge 1GB) { return ((T 'sz_gb') -f ($b / 1GB)) }
  if ($b -ge 1MB) { return ((T 'sz_mb') -f ($b / 1MB)) }
  return ((T 'sz_kb') -f ($b / 1KB))
}

$script:BaseDir = $PSScriptRoot
if (-not $script:BaseDir) { try { $script:BaseDir = Split-Path -Parent ([Environment]::GetCommandLineArgs()[0]) } catch {} }
if (-not $script:BaseDir -or -not (Test-Path -LiteralPath $script:BaseDir)) { $script:BaseDir = [Environment]::CurrentDirectory }
# Выбранных папок может быть несколько. Пустой список = работаем по $script:BaseDir
# (так продолжают работать тест-хуки, которые ставят только BaseDir).
$script:BaseDirs = @()
function CurrentRoots {
  $r = @($script:BaseDirs | Where-Object { $_ })
  if ($r.Count -eq 0) { $r = @($script:BaseDir) }
  return @($r | Where-Object { $_ -and (Test-Path -LiteralPath $_) })
}

# конфигурация (как в GUI-версии)
$JOBS    = 3
$VJOBS   = 4
$VJOBS_OVERLAP = 2
$ARC_BPP = 0.096
$EST_OVERHEAD = 1.15     # поправка прогноза: NVENC превышает целевой битрейт + контейнер
$PRESET  = 'p5'
$Modes = @(
  [pscustomobject]@{ Kind='old'; Ratio=55;  Floor=1500000; BppMin=0.0;      BppMax=0.15;     Ext=@('.avi','.wmv','.mts'); NameKey='mode_old_full' }
  [pscustomobject]@{ Kind='cam'; Ratio=45;  Floor=0;       BppMin=0.10;     BppMax=0.20;     Ext=@('.mp4','.mov');        NameKey='mode_cam_full' }
  [pscustomobject]@{ Kind='arc'; Ratio=100; Floor=0;       BppMin=$ARC_BPP; BppMax=$ARC_BPP; Ext=@('.mp4','.mov');        NameKey='mode_arc_full' }
)
$Codecs = @(
  [pscustomobject]@{ Key='av1';   Enc='av1_nvenc';  OutCodec='av1';   Gpu=$true;  Compress=$true;  Container='mp4';  Tag='';     Profile='' }
  [pscustomobject]@{ Key='hevc';  Enc='hevc_nvenc'; OutCodec='hevc';  Gpu=$true;  Compress=$true;  Container='keep'; Tag='hvc1'; Profile='' }
  [pscustomobject]@{ Key='dnxhr'; Enc='dnxhd';      OutCodec='dnxhd'; Gpu=$false; Compress=$false; Container='mov';  Tag='';     Profile='dnxhr_hqx' }
)
$SUFFIX = '_v2'
$script:ModeSel = 2
$script:CodecSel = 1     # HEVC по умолчанию: играет везде, в т.ч. на маке (у M1/M2 нет
                         # аппаратного декода AV1 — он появился только с M3)
$script:AudioSel = 0     # 0 = звук оригинала (без потерь), 1 = AAC стерео
function CurrentMode  { return $Modes[$script:ModeSel] }
function CurrentCodec { return $Codecs[$script:CodecSel] }
function OutName([System.IO.FileInfo]$fi, $mode) {
  $c = CurrentCodec; $base = $fi.BaseName + $SUFFIX
  if ($c.Container -eq 'mov') { return ($base + '.mov') }
  if ($c.Container -eq 'mp4') { return ($base + '.mp4') }
  if ($mode.Kind -eq 'old') { return ($base + '.mp4') }
  return ($base + $fi.Extension.ToLower())
}

# ---------------- логика конвейера (перенос из GUI-версии) ----------------
$LogFile = Join-Path $env:LOCALAPPDATA 'HEVC-Converter.log'
function Log([string]$m) { try { Add-Content -LiteralPath $LogFile -Value ("{0}  [WPF] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) -Encoding UTF8 } catch {} }
function Fail([string]$msg) {
  [System.Windows.MessageBox]::Show($msg, 'BitShift', [System.Windows.MessageBoxButton]::OK, [System.Windows.MessageBoxImage]::Error) | Out-Null
  Log "ошибка запуска: $msg"; exit 1
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
  Fail (T 'fail_ffmpeg')
}
$script:HasNvenc = [bool](& ffmpeg -hide_banner -encoders 2>$null | Select-String -SimpleMatch 'hevc_nvenc' -Quiet)
if (-not $script:HasNvenc) {
  Fail (T 'fail_nvenc')
}
# какая видеокарта в этой машине (у другого пользователя она будет своя)
function Detect-Gpu {
  $n = ''
  try { $n = [string](& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1) } catch {}
  if (-not $n) {
    try { $n = [string]((Get-CimInstance Win32_VideoController -ErrorAction Stop | Where-Object { $_.Name -match '(?i)nvidia' } | Select-Object -First 1).Name) } catch {}
  }
  if (-not $n) {
    try { $n = [string]((Get-CimInstance Win32_VideoController -ErrorAction Stop | Select-Object -First 1).Name) } catch {}
  }
  $n = ($n -replace '(?i)nvidia\s*', '' -replace '(?i)geforce\s*', '' -replace '(?i)\s*gpu$', '').Trim()
  if (-not $n) { $n = (T 'gpu_unknown') }
  return $n
}
$script:GpuName = Detect-Gpu
try {
  Add-Type -Name Sleeper -Namespace HevcWpf -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
'@
} catch {}
# пауза кодирования: на Windows нет SIGSTOP, приостанавливаем сам процесс ffmpeg
# (вместе с работой NVENC) через недокументированные, но стабильные ntdll-вызовы
try {
  Add-Type -Name ProcCtl -Namespace HevcWpf -MemberDefinition @'
[DllImport("ntdll.dll")] public static extern int NtSuspendProcess(System.IntPtr h);
[DllImport("ntdll.dll")] public static extern int NtResumeProcess(System.IntPtr h);
'@
} catch {}
function KeepAwake([bool]$on) {
  try {
    if ($on) { [HevcWpf.Sleeper]::SetThreadExecutionState([uint32]2147483651) | Out-Null }
    else     { [HevcWpf.Sleeper]::SetThreadExecutionState([uint32]2147483648) | Out-Null }
  } catch {}
}
$script:TMP = Join-Path $env:TEMP ("hevcconv-wpf-" + [IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $script:TMP -Force | Out-Null

function ProbeVideo([string]$f) {
  $j = (& ffprobe -v error -select_streams v:0 `
      -show_entries 'stream=codec_name,width,height,r_frame_rate,pix_fmt,bit_rate,color_primaries,color_transfer,color_space : format=duration,bit_rate' `
      -print_format json "$f" 2>$null) -join '' | ConvertFrom-Json
  $s = $null; if ($j -and $j.streams) { $s = $j.streams[0] }
  $o = New-Object psobject -Property @{ Codec=''; W=0; H=0; Fps=25.0; PixFmt=''; Prim=''; Trc=''; Csp=''; Dur=0.0; Bitrate=0 }
  if ($s) {
    $o.Codec = [string]$s.codec_name
    if ($s.width) { $o.W = [int]$s.width }; if ($s.height) { $o.H = [int]$s.height }
    $o.PixFmt = [string]$s.pix_fmt; $o.Prim = [string]$s.color_primaries; $o.Trc = [string]$s.color_transfer; $o.Csp = [string]$s.color_space
    $r = [string]$s.r_frame_rate
    if ($r -match '^(\d+)/(\d+)$') { if ([double]$Matches[2] -gt 0) { $o.Fps = [double]$Matches[1] / [double]$Matches[2] } }
    elseif ($r -match '^\d+(\.\d+)?$') { $o.Fps = [double]$r }
    if ($o.Fps -le 0) { $o.Fps = 25.0 }
    $sbr = [string]$s.bit_rate; if ($sbr -and $sbr -ne 'N/A') { $o.Bitrate = [long]$sbr }
  }
  if ($j -and $j.format) {
    $d = [string]$j.format.duration
    if ($d -and $d -ne 'N/A') { $o.Dur = [double]::Parse($d, [Globalization.CultureInfo]::InvariantCulture) }
    if ($o.Bitrate -eq 0) { $fbr = [string]$j.format.bit_rate; if ($fbr -and $fbr -ne 'N/A') { $o.Bitrate = [long]$fbr } }
  }
  if ($o.Bitrate -eq 0) { $o.Bitrate = 8000000 }
  return $o
}
function AudioInfo([string]$f) {
  $o = New-Object psobject -Property @{ Codec=''; Chans=0; Rate=0; Bits=0; Bitrate=0 }
  $j = (& ffprobe -v error -select_streams a:0 -show_entries 'stream=codec_name,channels,sample_rate,bits_per_raw_sample,bit_rate' -print_format json "$f" 2>$null) -join ''
  if ($j) {
    try {
      $p = $j | ConvertFrom-Json
      if ($p -and $p.streams -and $p.streams.Count -gt 0) {
        $s = $p.streams[0]
        $o.Codec = [string]$s.codec_name
        if ($s.channels) { $o.Chans = [int]$s.channels }
        if ($s.sample_rate) { $o.Rate = [int]$s.sample_rate }
        if ($s.bits_per_raw_sample -and "$($s.bits_per_raw_sample)" -match '^\d+$') { $o.Bits = [int]$s.bits_per_raw_sample }
        if ($s.bit_rate -and "$($s.bit_rate)" -match '^\d+$') { $o.Bitrate = [long]$s.bit_rate }
      }
    } catch {}
  }
  # у PCM битрейт в метаданных часто пуст — считаем из частоты, разрядности и каналов
  if ($o.Bitrate -le 0 -and $o.Codec -like 'pcm*' -and $o.Rate -gt 0 -and $o.Chans -gt 0) {
    $b = $o.Bits; if ($b -le 0) { $b = 16 }
    $o.Bitrate = [long]($o.Rate * $b * $o.Chans)
  }
  return $o
}
# Что делать со звуком — выбирает пользователь (секция ЗВУК):
#   0 «Оригинал»   — копируем как есть, все каналы и разрядность целы;
#   1 «AAC стерео» — сводим в стерео 256k. Именно -ac 2 обходит ограничение
#     встроенного AAC-энкодера (больше 8 каналов он не умеет: 16-канальная
#     многодорожка падала с «Unsupported channel layout 9.1.6»).
# $item.AudioForce — аварийный откат, когда исходный звук не лёг в контейнер.
function AudioArgs($item) {
  $mode = 'orig'; if ($script:AudioSel -eq 1) { $mode = 'aac' }
  if ($item.AudioForce) { $mode = [string]$item.AudioForce }
  if ($mode -eq 'orig') { return '-c:a copy ' }
  # уже стерео/моно AAC перекодировать незачем — только потеря качества
  if ($item.ACodec -eq 'aac' -and [int]$item.AChans -le 2) { return '-c:a copy ' }
  return '-c:a aac -b:a 256k -ac 2 '
}
# из stderr ffmpeg берём именно ОШИБКУ, а не первое попавшееся предупреждение
# (например «Guessed Channel Layout» — это просто информация, а не сбой)
function ErrSummary([string]$file) {
  $lines = @()
  try { $lines = @(Get-Content -LiteralPath $file -ErrorAction SilentlyContinue | Where-Object { $_ -and $_.Trim() }) } catch {}
  if ($lines.Count -eq 0) { return (T 'err_none') }
  $bad = @($lines | Where-Object { $_ -notmatch '(?i)Guessed Channel Layout' -and $_ -match '(?i)(error|unsupported|invalid|failed|not supported|no space|denied|cannot|could not)' })
  if ($bad.Count -gt 0) { return (($bad | Select-Object -First 2) -join ' | ') }
  return (($lines | Select-Object -Last 2) -join ' | ')
}
function PacketCount([string]$f) {
  $n = & ffprobe -v error -count_packets -select_streams v:0 -show_entries stream=nb_read_packets -of 'default=noprint_wrappers=1:nokey=1' "$f" 2>$null
  if ($n -is [array]) { $n = $n[0] }; if ($n -match '^\d+$') { return [long]$n }; return -1
}
function Q([string]$s) { return '"' + $s + '"' }
function IsSlowDrive([string]$path) {
  if ($env:HEVC_WPF_FORCESTAGE -eq '1') { return $true }
  try {
    if ($path -like '\\*') { return $true }
    $root = [IO.Path]::GetPathRoot($path).TrimEnd('\')
    if ($root -notmatch '^[A-Za-z]:$') { return $false }
    $part = Get-Partition -DriveLetter $root[0] -ErrorAction Stop
    $disk = Get-Disk -Number $part.DiskNumber -ErrorAction Stop
    return ($disk.BusType -eq 'USB')
  } catch { return $false }
}
# то же, но с запоминанием по корню пути: Get-Partition/Get-Disk дёргать на каждый
# файл дорого, а диск в пределах запуска не меняется
$script:SlowCache = @{}
function IsSlowPath([string]$path) {
  if (-not $path) { return $false }
  $key = $path
  try { $r = [IO.Path]::GetPathRoot($path); if ($r) { $key = $r } } catch {}
  $key = $key.ToLower()
  if ($script:SlowCache.ContainsKey($key)) { return $script:SlowCache[$key] }
  $v = IsSlowDrive $path
  $script:SlowCache[$key] = $v
  return $v
}
function StartRobocopy([string]$fromDir, [string]$toDir, [string]$name, [bool]$move) {
  $mv = ''; if ($move) { $mv = '/MOV ' }
  $a = "$(Q $fromDir) $(Q $toDir) $(Q $name) $mv/NJH /NJS /NDL /NFL /R:2 /W:2"
  $p = Start-Process -FilePath 'robocopy' -ArgumentList $a -WindowStyle Hidden -PassThru
  $null = $p.Handle; return $p
}

# ---------------- XAML ----------------
$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="BitShift" Height="700" Width="900" MinHeight="672" MinWidth="820"
        WindowStartupLocation="CenterScreen" Background="#0A0A0C"
        WindowStyle="None" ResizeMode="CanResize"
        FontFamily="Segoe UI" TextOptions.TextFormattingMode="Display" UseLayoutRounding="True">
  <Window.Resources>
    <SolidColorBrush x:Key="Tx"  Color="#F0F0F3"/>
    <SolidColorBrush x:Key="Tx2" Color="#97979F"/>
    <SolidColorBrush x:Key="Tx3" Color="#66666E"/>
    <SolidColorBrush x:Key="Panel" Color="#17171B"/>
    <SolidColorBrush x:Key="Rail"  Color="#141418"/>
    <SolidColorBrush x:Key="Raise" Color="#1E1E23"/>
    <SolidColorBrush x:Key="Line"  Color="#2A2A31"/>
    <SolidColorBrush x:Key="Pill"  Color="#26262D"/>

    <!-- иконка пункта: обводка тянется за Foreground пункта, поэтому активная
         подсвечивается вместе с подписью, а неактивные остаются тусклыми -->
    <Style x:Key="NavIcon" TargetType="Path">
      <Setter Property="Width" Value="16"/>
      <Setter Property="Height" Value="16"/>
      <Setter Property="Stretch" Value="None"/>
      <Setter Property="StrokeThickness" Value="1.4"/>
      <Setter Property="StrokeStartLineCap" Value="Round"/>
      <Setter Property="StrokeEndLineCap" Value="Round"/>
      <Setter Property="StrokeLineJoin" Value="Round"/>
      <Setter Property="VerticalAlignment" Value="Center"/>
      <Setter Property="Margin" Value="0,0,11,0"/>
      <Setter Property="Stroke" Value="{Binding Foreground, RelativeSource={RelativeSource AncestorType={x:Type RadioButton}}}"/>
    </Style>

    <Style x:Key="Nav" TargetType="RadioButton">
      <Setter Property="Foreground" Value="{StaticResource Tx2}"/>
      <Setter Property="FontSize" Value="13.5"/>
      <Setter Property="SnapsToDevicePixels" Value="True"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RadioButton">
            <!-- активный пункт: тёмная пилюля, плавно уходящая в фирменную магенту.
                 Никаких кромок и маркеров — градиента достаточно, чтобы выделить пункт -->
            <Border x:Name="b" Background="Transparent" CornerRadius="10" Padding="12,7" Margin="0,1">
              <ContentPresenter VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="b" Property="Background" Value="#16FFFFFF"/>
              </Trigger>
              <Trigger Property="IsChecked" Value="True">
                <Setter Property="Foreground" Value="{StaticResource Tx}"/>
                <Setter TargetName="b" Property="Background">
                  <Setter.Value>
                    <LinearGradientBrush StartPoint="0,0" EndPoint="1,0">
                      <GradientStop Color="#242430" Offset="0"/>
                      <GradientStop Color="#3A2039" Offset="0.5"/>
                      <GradientStop Color="#8E1A58" Offset="0.82"/>
                      <GradientStop Color="#DB1671" Offset="1"/>
                    </LinearGradientBrush>
                  </Setter.Value>
                </Setter>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Flat" TargetType="Button">
      <Setter Property="Foreground" Value="{StaticResource Tx2}"/>
      <Setter Property="FontSize" Value="12.5"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" Background="{StaticResource Panel}" BorderBrush="{StaticResource Line}" BorderThickness="1" CornerRadius="9" Padding="14,7">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Background" Value="{StaticResource Pill}"/><Setter Property="Foreground" Value="{StaticResource Tx}"/></Trigger>
              <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.4"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Primary" TargetType="Button">
      <Setter Property="Foreground" Value="#111114"/>
      <Setter Property="FontSize" Value="13.5"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" Background="#F0F0F3" CornerRadius="11" Padding="22,10">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Background" Value="#FFFFFF"/></Trigger>
              <Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.4"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Bar" TargetType="ProgressBar">
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ProgressBar">
            <Border Background="{StaticResource Pill}" CornerRadius="4">
              <Border x:Name="PART_Indicator" HorizontalAlignment="Left" CornerRadius="4">
                <Border.Background>
                  <LinearGradientBrush StartPoint="0,0" EndPoint="1,0"><GradientStop Color="#C8C8CF" Offset="0"/><GradientStop Color="#FFFFFF" Offset="1"/></LinearGradientBrush>
                </Border.Background>
              </Border>
            </Border>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="Row" TargetType="ListBoxItem">
      <Setter Property="Padding" Value="0"/>
      <Setter Property="HorizontalContentAlignment" Value="Stretch"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ListBoxItem">
            <Border x:Name="b" Background="Transparent" CornerRadius="8" Padding="6,2">
              <ContentPresenter/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Background" Value="#12FFFFFF"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="WinBtn" TargetType="Button">
      <Setter Property="Foreground" Value="{StaticResource Tx2}"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Width" Value="34"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" Background="Transparent" CornerRadius="8">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Background" Value="{StaticResource Pill}"/><Setter Property="Foreground" Value="{StaticResource Tx}"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="WinClose" TargetType="Button">
      <Setter Property="Foreground" Value="{StaticResource Tx2}"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Width" Value="34"/>
      <Setter Property="Height" Value="28"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" Background="Transparent" CornerRadius="8">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Background" Value="#E8756F"/><Setter Property="Foreground" Value="#111114"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style x:Key="ScrollThumb" TargetType="Thumb">
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Thumb">
            <Border x:Name="b" Background="#3A3A42" CornerRadius="4" Margin="2,0"/>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True"><Setter TargetName="b" Property="Background" Value="#50505A"/></Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style TargetType="ScrollBar">
      <Setter Property="Width" Value="10"/>
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ScrollBar">
            <Grid Background="Transparent">
              <Track x:Name="PART_Track" IsDirectionReversed="True">
                <Track.DecreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageUpCommand" Opacity="0" Focusable="False" IsTabStop="False"/>
                </Track.DecreaseRepeatButton>
                <Track.Thumb>
                  <Thumb Style="{StaticResource ScrollThumb}"/>
                </Track.Thumb>
                <Track.IncreaseRepeatButton>
                  <RepeatButton Command="ScrollBar.PageDownCommand" Opacity="0" Focusable="False" IsTabStop="False"/>
                </Track.IncreaseRepeatButton>
              </Track>
            </Grid>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid x:Name="Root" Margin="14">
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="252"/>
      <ColumnDefinition Width="16"/>
      <ColumnDefinition Width="*"/>
    </Grid.ColumnDefinitions>

    <!-- рейл -->
    <Border Grid.Column="0" Background="{StaticResource Rail}" CornerRadius="16">
      <Border.Effect><DropShadowEffect Color="#000000" BlurRadius="30" ShadowDepth="0" Opacity="0.55"/></Border.Effect>
      <DockPanel Margin="16,18">
        <StackPanel DockPanel.Dock="Top">
          <StackPanel Orientation="Horizontal">
            <!-- логотип — та же картинка, что и иконка приложения (bitshift-source.png),
                 зашита в скрипт как base64, чтобы exe оставался самодостаточным -->
            <Image x:Name="ImgLogo" Width="36" Height="36" VerticalAlignment="Center" Margin="0,0,11,0"
                   RenderOptions.BitmapScalingMode="HighQuality"/>
            <StackPanel VerticalAlignment="Center">
              <TextBlock Text="BitShift" Foreground="{StaticResource Tx}" FontSize="17" FontWeight="SemiBold"/>
              <TextBlock x:Name="LblDevice" Text="—" Foreground="{StaticResource Tx3}" FontSize="11" Margin="0,1,0,0"
                         TextTrimming="CharacterEllipsis" MaxWidth="150"/>
            </StackPanel>
          </StackPanel>
          <!-- выбранная папка: просто подпись, полный путь — в подсказке.
               Выбор папки делается кнопкой «Обзор…» -->
          <TextBlock x:Name="TxtFolder" Text="—" Foreground="{StaticResource Tx2}" FontSize="12"
                     Margin="1,15,0,0" TextTrimming="CharacterEllipsis"/>

          <TextBlock x:Name="LblSecMode" Text="РЕЖИМ" Foreground="{StaticResource Tx3}" FontSize="10.5" Margin="0,16,0,5"/>
          <RadioButton x:Name="Mode0" GroupName="M" Style="{StaticResource Nav}"
                       ToolTip="Файлы AVI, WMV, MTS — старые камеры и видеокассеты. Результат в MP4.">
            <StackPanel Orientation="Horizontal">
              <Path Style="{StaticResource NavIcon}" Data="M1.5,3.5 H14.5 V12.5 H1.5 Z M4.5,3.5 V12.5 M11.5,3.5 V12.5"/>
              <TextBlock x:Name="LblMode0" Text="Старое видео" VerticalAlignment="Center"/>
            </StackPanel>
          </RadioButton>
          <RadioButton x:Name="Mode1" GroupName="M" Style="{StaticResource Nav}"
                       ToolTip="MP4/MOV прямо с камеры (Log, S-Log3, плоская картинка).&#10;Сжимает бережнее: сохраняет 10 бит и цвет для дальнейшей обработки.">
            <StackPanel Orientation="Horizontal">
              <Path Style="{StaticResource NavIcon}" Data="M1.5,4.5 H9.5 V11.5 H1.5 Z M9.5,7 L14.5,4.5 V11.5 L9.5,9 Z"/>
              <TextBlock x:Name="LblMode1" Text="Съёмка с камеры" VerticalAlignment="Center"/>
            </StackPanel>
          </RadioButton>
          <RadioButton x:Name="Mode2" GroupName="M" Style="{StaticResource Nav}" IsChecked="True"
                       ToolTip="MP4/MOV: смонтированные ролики, съёмки с телефона, архив.&#10;Максимальная экономия места. Уже компактные файлы пропускаются.">
            <StackPanel Orientation="Horizontal">
              <Path Style="{StaticResource NavIcon}" Data="M1.5,3.5 H14.5 V6.5 H1.5 Z M2.8,6.5 V12.5 H13.2 V6.5 M6.3,9.3 H9.7"/>
              <TextBlock x:Name="LblMode2" Text="Обычное видео" VerticalAlignment="Center"/>
            </StackPanel>
          </RadioButton>

          <TextBlock x:Name="LblSecCodec" Text="КОДЕК" Foreground="{StaticResource Tx3}" FontSize="10.5" Margin="0,17,0,5"/>
          <RadioButton x:Name="Codec0" GroupName="C" Style="{StaticResource Nav}">
            <StackPanel Orientation="Horizontal">
              <Path Style="{StaticResource NavIcon}" Data="M9,1.5 L3.5,8.8 H7.2 L6.4,14.5 L12.5,7.2 H8.8 Z"/>
              <TextBlock x:Name="LblCodec0" Text="AV1" VerticalAlignment="Center"/>
            </StackPanel>
          </RadioButton>
          <RadioButton x:Name="Codec1" GroupName="C" Style="{StaticResource Nav}" IsChecked="True">
            <StackPanel Orientation="Horizontal">
              <Path Style="{StaticResource NavIcon}" Data="M8,1.5 L13.5,3.8 V8 C13.5,11.2 11,13.4 8,14.5 C5,13.4 2.5,11.2 2.5,8 V3.8 Z"/>
              <TextBlock x:Name="LblCodec1" Text="HEVC" VerticalAlignment="Center"/>
            </StackPanel>
          </RadioButton>
          <RadioButton x:Name="Codec2" GroupName="C" Style="{StaticResource Nav}">
            <StackPanel Orientation="Horizontal">
              <Path Style="{StaticResource NavIcon}" Data="M8,1.8 C8,1.8 3.2,7.2 3.2,10 A4.8,4.8 0 0 0 12.8,10 C12.8,7.2 8,1.8 8,1.8 Z"/>
              <TextBlock x:Name="LblCodec2" Text="DNxHR" VerticalAlignment="Center"/>
            </StackPanel>
          </RadioButton>

          <TextBlock x:Name="LblSecAudio" Text="ЗВУК" Foreground="{StaticResource Tx3}" FontSize="10.5" Margin="0,17,0,5"/>
          <RadioButton x:Name="Audio0" GroupName="A" Style="{StaticResource Nav}" IsChecked="True">
            <StackPanel Orientation="Horizontal">
              <Path Style="{StaticResource NavIcon}" Data="M2.5,6 V10 M6,2.8 V13.2 M9.5,4.8 V11.2 M13,6.3 V9.7"/>
              <TextBlock x:Name="LblAudio0" Text="Оригинал" VerticalAlignment="Center"/>
            </StackPanel>
          </RadioButton>
          <RadioButton x:Name="Audio1" GroupName="A" Style="{StaticResource Nav}">
            <StackPanel Orientation="Horizontal">
              <Path Style="{StaticResource NavIcon}" Data="M2,6.2 H5 L9,3 V13 L5,9.8 H2 Z M11.6,6.2 A3.4,3.4 0 0 1 11.6,9.8"/>
              <TextBlock x:Name="LblAudio1" Text="AAC" VerticalAlignment="Center"/>
            </StackPanel>
          </RadioButton>
        </StackPanel>
        <!-- шестерёнка внизу рейла: редкие настройки спрятаны сюда, чтобы не шуметь
             в основном экране. Всплывающая карточка появляется над значком -->
        <Grid DockPanel.Dock="Bottom" Margin="0,0,0,8" HorizontalAlignment="Left">
          <Border x:Name="BtnGear" Background="Transparent" CornerRadius="8" Padding="5" Cursor="Hand"
                  ToolTip="Настройки">
            <Grid Width="18" Height="18">
              <Path x:Name="GearTeeth" Fill="{StaticResource Tx2}" Data="F0 M15.67,9.67 L17.48,10.42 L16,13.99 L14.19,13.24 L13.24,14.19 L13.99,16 L10.42,17.48 L9.67,15.67 L8.33,15.67 L7.58,17.48 L4.01,16 L4.76,14.19 L3.81,13.24 L2,13.99 L0.52,10.42 L2.33,9.67 L2.33,8.33 L0.52,7.58 L2,4.01 L3.81,4.76 L4.76,3.81 L4.01,2 L7.58,0.52 L8.33,2.33 L9.67,2.33 L10.42,0.52 L13.99,2 L13.24,3.81 L14.19,4.76 L16,4.01 L17.48,7.58 L15.67,8.33 Z M6.15,9 A2.85,2.85 0 1 0 11.85,9 A2.85,2.85 0 1 0 6.15,9 Z"/>
            </Grid>
          </Border>
          <Popup x:Name="PopSettings" PlacementTarget="{Binding ElementName=BtnGear}" Placement="Top"
                 VerticalOffset="-8" HorizontalOffset="-4" StaysOpen="False" AllowsTransparency="True"
                 PopupAnimation="Fade">
            <Border Background="#1C1C22" BorderBrush="{StaticResource Line}" BorderThickness="1"
                    CornerRadius="12" Padding="15,13" Width="316">
              <Border.Effect><DropShadowEffect Color="#000000" BlurRadius="26" ShadowDepth="3" Opacity="0.65"/></Border.Effect>
              <StackPanel>
                <TextBlock x:Name="LblSettings" Text="НАСТРОЙКИ" Foreground="{StaticResource Tx3}" FontSize="10.5" Margin="0,0,0,11"/>
                <TextBlock x:Name="LblLangLabel" Text="Язык" Foreground="{StaticResource Tx2}" FontSize="11.5" Margin="0,0,0,6"/>
                <StackPanel Orientation="Horizontal" Margin="0,0,0,14">
                  <TextBlock x:Name="LnkRu" Text="RU" FontSize="12.5" Cursor="Hand"/>
                  <TextBlock Text="·" Foreground="{StaticResource Tx3}" FontSize="12.5" Margin="9,0,9,0"/>
                  <TextBlock x:Name="LnkEn" Text="EN" FontSize="12.5" Cursor="Hand"/>
                </StackPanel>
                <Border Height="1" Background="{StaticResource Line}" Margin="0,0,0,13"/>
                <CheckBox x:Name="ChkAuto" Content="Удалять исходники в Корзину после проверки" IsChecked="True"
                          Foreground="{StaticResource Tx2}" FontSize="11.5" Margin="0,0,0,10" TextBlock.LineHeight="15"/>
                <CheckBox x:Name="ChkShutdown" Content="Выключить компьютер после завершения"
                          Foreground="{StaticResource Tx2}" FontSize="11.5"/>
              </StackPanel>
            </Border>
          </Popup>
        </Grid>
        <CheckBox x:Name="ChkSub" DockPanel.Dock="Bottom" Content="Включая подпапки" Foreground="{StaticResource Tx2}" FontSize="11.5" Margin="2,0,0,2"/>
        <StackPanel x:Name="StatsPanel" DockPanel.Dock="Bottom" Margin="2,0,0,12">
          <TextBlock x:Name="LblSecVolume" Text="ОБЪЁМ" Foreground="{StaticResource Tx3}" FontSize="10.5" Margin="0,0,0,5"/>
          <TextBlock x:Name="LblSrcTotal" Foreground="{StaticResource Tx2}" FontSize="12" Text="—"/>
          <TextBlock x:Name="LblSaved" Foreground="{StaticResource Tx2}" FontSize="12" Margin="0,3,0,0"/>
          <TextBlock x:Name="LblSecLeft" Text="ОСТАЛОСЬ" Foreground="{StaticResource Tx3}" FontSize="10.5" Margin="0,12,0,5"/>
          <TextBlock x:Name="LblEta" Foreground="{StaticResource Tx}" FontSize="13.5" Text="—"/>
        </StackPanel>
        <Grid/>
      </DockPanel>
    </Border>

    <!-- главная панель -->
    <Border Grid.Column="2" Background="{StaticResource Panel}" CornerRadius="16">
      <Border.Effect><DropShadowEffect Color="#000000" BlurRadius="30" ShadowDepth="0" Opacity="0.55"/></Border.Effect>
      <Grid Margin="20,18,20,18">
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <Grid Grid.Row="0">
          <StackPanel>
            <TextBlock x:Name="LblTitle" Text="Исходники шоу" Foreground="{StaticResource Tx}" FontSize="17" FontWeight="SemiBold"/>
            <TextBlock x:Name="LblCount" Foreground="{StaticResource Tx3}" FontSize="11.5" Margin="0,2,0,0"/>
          </StackPanel>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" VerticalAlignment="Top">
            <Button x:Name="BtnBrowse" Style="{StaticResource Flat}" Content="Обзор…" Margin="0,0,8,0"/>
            <Button x:Name="BtnRefresh" Style="{StaticResource Flat}" Content="Обновить"/>
            <Button x:Name="BtnMin" Style="{StaticResource WinBtn}" Content="&#x2013;" Margin="16,0,0,0"/>
            <Button x:Name="BtnClose" Style="{StaticResource WinClose}" Content="&#x2715;" Margin="4,0,0,0"/>
          </StackPanel>
        </Grid>

        <ListBox x:Name="Lv" Grid.Row="1" Margin="0,14,0,0" Background="Transparent" BorderThickness="0"
                 ScrollViewer.HorizontalScrollBarVisibility="Disabled"
                 ItemContainerStyle="{StaticResource Row}">
          <ListBox.ItemTemplate>
            <DataTemplate>
              <Grid>
                <Grid.ColumnDefinitions>
                  <ColumnDefinition Width="Auto"/>
                  <ColumnDefinition Width="*"/>
                  <ColumnDefinition Width="Auto"/>
                  <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <CheckBox Grid.Column="0" IsChecked="{Binding IsChecked, Mode=TwoWay}" IsEnabled="{Binding CanCheck}" VerticalAlignment="Center" Margin="2,0,12,0"/>
                <StackPanel Grid.Column="1" VerticalAlignment="Center">
                  <TextBlock Text="{Binding Name}" Foreground="#F0F0F3" FontSize="13"/>
                  <TextBlock Text="{Binding Info}" Foreground="#66666E" FontSize="11"/>
                  <!-- шкала текущего этапа: копирование / кодирование / проверка / перенос -->
                  <Border Height="3" Width="300" HorizontalAlignment="Left" Background="#1E1E23" CornerRadius="2" Margin="0,4,0,0">
                    <Border HorizontalAlignment="Left" Width="{Binding BarWidth}" Background="{Binding BarColor}" CornerRadius="2"/>
                  </Border>
                </StackPanel>
                <TextBlock Grid.Column="2" Text="{Binding Size}" Foreground="#97979F" FontSize="12" VerticalAlignment="Center" Margin="12,0"/>
                <Border Grid.Column="3" Background="#22262D" CornerRadius="9" Padding="10,3" MinWidth="130" VerticalAlignment="Center" ToolTip="{Binding Status}">
                  <TextBlock Text="{Binding Status}" Foreground="{Binding StatusColor}" FontSize="12" TextAlignment="Center"/>
                </Border>
              </Grid>
            </DataTemplate>
          </ListBox.ItemTemplate>
        </ListBox>

        <StackPanel Grid.Row="2" Margin="0,16,0,0">
          <Border x:Name="BarTrack" Height="10" Background="{StaticResource Pill}" CornerRadius="5">
            <Border x:Name="BarFill" HorizontalAlignment="Left" CornerRadius="5" Width="0">
              <Border.Background>
                <LinearGradientBrush StartPoint="0,0" EndPoint="1,0"><GradientStop Color="#C8C8CF" Offset="0"/><GradientStop Color="#FFFFFF" Offset="1"/></LinearGradientBrush>
              </Border.Background>
            </Border>
          </Border>
          <TextBlock x:Name="LblStatus" Margin="0,11,0,0" Foreground="{StaticResource Tx2}" FontSize="12"
                     Text="Оригиналы не перезаписываются. Удаление — только в Корзину, после проверки."/>
        </StackPanel>

        <Grid Grid.Row="3" Margin="0,18,0,0">
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Left" VerticalAlignment="Bottom">
            <Button x:Name="BtnStart" Style="{StaticResource Primary}" Content="Старт" Margin="0,0,10,0"/>
            <Button x:Name="BtnPause" Style="{StaticResource Flat}" Content="Пауза" IsEnabled="False" Margin="0,0,10,0"/>
            <Button x:Name="BtnStop" Style="{StaticResource Flat}" Content="Стоп" IsEnabled="False"/>
          </StackPanel>
          <StackPanel HorizontalAlignment="Right" VerticalAlignment="Bottom">
            <Button x:Name="BtnDelete" Style="{StaticResource Flat}" Content="Удалить проверенные в Корзину…" HorizontalAlignment="Right" IsEnabled="False"/>
          </StackPanel>
        </Grid>
      </Grid>
    </Border>
  </Grid>
</Window>
'@

$reader = New-Object System.Xml.XmlNodeReader ([xml]$xaml)
$Window = [System.Windows.Markup.XamlReader]::Load($reader)

$Lv        = $Window.FindName('Lv')
$BarTrack  = $Window.FindName('BarTrack')
$BarFill   = $Window.FindName('BarFill')
$LblStatus = $Window.FindName('LblStatus')
$LblTitle  = $Window.FindName('LblTitle')
$LblCount  = $Window.FindName('LblCount')
$TxtFolder = $Window.FindName('TxtFolder')
$LblDevice = $Window.FindName('LblDevice')
$LblSecMode   = $Window.FindName('LblSecMode')
$LblSecCodec  = $Window.FindName('LblSecCodec')
$LblSecAudio  = $Window.FindName('LblSecAudio')
$LblSecVolume = $Window.FindName('LblSecVolume')
$LblSecLeft   = $Window.FindName('LblSecLeft')
$LblMode0 = $Window.FindName('LblMode0'); $LblMode1 = $Window.FindName('LblMode1'); $LblMode2 = $Window.FindName('LblMode2')
$LblCodec0 = $Window.FindName('LblCodec0'); $LblCodec1 = $Window.FindName('LblCodec1'); $LblCodec2 = $Window.FindName('LblCodec2')
$LblAudio0 = $Window.FindName('LblAudio0'); $LblAudio1 = $Window.FindName('LblAudio1')
$LnkRu = $Window.FindName('LnkRu'); $LnkEn = $Window.FindName('LnkEn')
$BtnGear = $Window.FindName('BtnGear'); $PopSettings = $Window.FindName('PopSettings')
$GearTeeth = $Window.FindName('GearTeeth')
$LblSettings = $Window.FindName('LblSettings'); $LblLangLabel = $Window.FindName('LblLangLabel')
$ImgLogo   = $Window.FindName('ImgLogo')
# логотип рейла: та же картинка, что и иконка (кроп плитки из bitshift-source.png),
# зашита сюда base64 — иначе exe зависел бы от внешнего файла
$script:LogoB64 = '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'
try {
  if ($script:LogoB64 -and $script:LogoB64 -ne 'PLACEHOLDER_LOGO_B64') {
    $lb = [Convert]::FromBase64String($script:LogoB64)
    $ms = New-Object System.IO.MemoryStream(,$lb)
    $bi = New-Object System.Windows.Media.Imaging.BitmapImage
    $bi.BeginInit(); $bi.StreamSource = $ms
    $bi.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
    $bi.EndInit(); $bi.Freeze()
    $ImgLogo.Source = $bi
  }
} catch { Log "логотип не загрузился: $_" }
$ChkSub    = $Window.FindName('ChkSub')
$BtnBrowse = $Window.FindName('BtnBrowse')
$BtnRefresh= $Window.FindName('BtnRefresh')
$BtnStart  = $Window.FindName('BtnStart')
$BtnPause  = $Window.FindName('BtnPause')
$BtnStop   = $Window.FindName('BtnStop')
$BtnDelete = $Window.FindName('BtnDelete')
$LblSrcTotal = $Window.FindName('LblSrcTotal')
$LblSaved    = $Window.FindName('LblSaved')
$LblEta      = $Window.FindName('LblEta')
$ChkAuto   = $Window.FindName('ChkAuto')
$ChkShutdown = $Window.FindName('ChkShutdown')
$BtnMin    = $Window.FindName('BtnMin')
$BtnClose  = $Window.FindName('BtnClose')
$script:ModeBtns  = @(0..2 | ForEach-Object { $Window.FindName("Mode$_") })
$script:CodecBtns = @(0..2 | ForEach-Object { $Window.FindName("Codec$_") })
$script:AudioBtns = @(0..1 | ForEach-Object { $Window.FindName("Audio$_") })

# безрамочное окно: своя «шапка» (перетаскивание/ресайз через WindowChrome),
# свои кнопки свернуть/закрыть
$chrome = New-Object System.Windows.Shell.WindowChrome
$chrome.CaptionHeight = 34
$chrome.ResizeBorderThickness = New-Object System.Windows.Thickness 6
$chrome.GlassFrameThickness = New-Object System.Windows.Thickness 0
$chrome.CornerRadius = New-Object System.Windows.CornerRadius 0
[System.Windows.Shell.WindowChrome]::SetWindowChrome($Window, $chrome)
foreach ($b in @($BtnBrowse, $BtnRefresh, $BtnMin, $BtnClose)) { [System.Windows.Shell.WindowChrome]::SetIsHitTestVisibleInChrome($b, $true) }
$BtnMin.Add_Click({ $Window.WindowState = 'Minimized' })
$BtnClose.Add_Click({ $Window.Close() })

$script:Rows = New-Object System.Collections.ObjectModel.ObservableCollection[object]
$Lv.ItemsSource = $script:Rows
$script:Phase = 'idle'

function Set-ItemStatus($row, [string]$text, $brush) {
  $row.Status = $text
  if ($brush) { $row.StatusColor = $brush } else { $row.StatusColor = $ClrTx2 }
}
# мини-шкала в строке: $pct 0..100, $brush = цвет этапа. $pct < 0 — спрятать шкалу.
function Set-RowBar($row, [double]$pct, $brush) {
  if ($pct -lt 0) { $row.BarWidth = 0.0; return }
  if ($pct -gt 100) { $pct = 100 }
  if ($brush) { $row.BarColor = $brush }
  $row.BarWidth = [math]::Round($ROWBAR_W * $pct / 100.0)
}
# доля скопированного: сравниваем размер файла-назначения с исходным
function CopyPct([string]$dest, [long]$srcLen) {
  if ($srcLen -le 0) { return 0 }
  try { if (Test-Path -LiteralPath $dest) { return [math]::Min(100, (Get-Item -LiteralPath $dest).Length * 100.0 / $srcLen) } } catch {}
  return 0
}
# доля обработанного по -progress файлу ffmpeg (out_time_us) относительно длительности
function ProgPct([string]$progFile, [double]$dur) {
  if ($dur -le 0) { return -1 }
  try {
    $txt = Get-Content -LiteralPath $progFile -Tail 20 -ErrorAction SilentlyContinue
    $ln = @($txt | Where-Object { $_ -like 'out_time_us=*' })
    if ($ln.Count -gt 0) { return [math]::Min(100, ([double]($ln[-1] -replace 'out_time_us=', '')) / 10000.0 / $dur) }
  } catch {}
  return -1
}

function Refresh-FileList {
  $mode = CurrentMode
  $script:Rows.Clear()
  $roots = CurrentRoots
  if ($roots.Count -eq 0) { return }
  $recurse = ($ChkSub -and $ChkSub.IsChecked -eq $true)
  $multi = ($roots.Count -gt 1)
  $seenOuts = @{}; $nNew = 0; $nReady = 0; $nTotal = 0
  foreach ($root in $roots) {
  $base = $root.TrimEnd('\')
  $cand = @(Get-ChildItem -LiteralPath $root -File -Recurse:$recurse -ErrorAction SilentlyContinue |
            Where-Object { $mode.Ext -contains $_.Extension.ToLower() } | Sort-Object FullName)
  $nTotal += $cand.Count
  foreach ($fi in $cand) {
    if ($fi.BaseName.ToLower().EndsWith($SUFFIX)) { continue }
    $out = Join-Path $fi.DirectoryName (OutName $fi $mode)
    $row = New-Object FileRow
    # имя = путь относительно выбранной папки (в рекурсии показывает подпапку).
    # Если выбрано несколько папок — впереди имя корневой, чтобы строки различались.
    $rel = $fi.FullName; if ($rel.Length -gt $base.Length) { $rel = $rel.Substring($base.Length).TrimStart('\') }
    if ($multi) { $rel = (Split-Path $base -Leaf) + '\' + $rel }
    $row.Name = $rel; $row.Size = (HumanSize $fi.Length); $row.Info = ''
    if (Test-Path -LiteralPath $out) {
      $skip = ''
      $codec = CurrentCodec
      if ($codec.Compress) {
        $p0 = ProbeVideo $fi.FullName
        if ($mode.Kind -eq 'cam' -and $p0.Codec -eq 'hevc') { $skip = (T 'ready_hevc') }
        elseif ($mode.Kind -eq 'arc') {
          $px0 = [double]$p0.W * $p0.H * $p0.Fps
          if ($px0 -gt 0 -and $p0.Bitrate -gt 0 -and $p0.Bitrate -le $px0 * $ARC_BPP * 1.12) { $skip = (T 'ready_compact') }
        }
      }
      if ($skip) {
        $row.Tag = @{ Kind='skip'; Path=$fi.FullName; Out=$out; Locked=$true; Bytes=$fi.Length }
        $row.CanCheck = $false; $row.IsChecked = $false
        Set-ItemStatus $row $skip $ClrTx2
      } else {
        $row.Tag = @{ Kind='pair'; Path=$fi.FullName; Out=$out; Locked=$true; Bytes=$fi.Length }
        $row.CanCheck = $false; $row.IsChecked = $true
        Set-ItemStatus $row (T 'st_ready_pair') $ClrTx2; $nReady++
      }
    } else {
      $key = $out.ToLower()
      if ($seenOuts.ContainsKey($key)) {
        $row.Tag = @{ Kind='collision'; Path=$fi.FullName; Out=$out; Locked=$true; Bytes=$fi.Length }
        $row.CanCheck = $false; $row.IsChecked = $false
        Set-ItemStatus $row (T 'st_collision') $ClrRed
      } else {
        $seenOuts[$key] = $true
        $row.Tag = @{ Kind='new'; Path=$fi.FullName; Out=$out; Locked=$false; Bytes=$fi.Length }
        $row.CanCheck = $true; $row.IsChecked = $true
        Set-ItemStatus $row (T 'st_queued') $ClrTx2; $nNew++
      }
    }
    $script:Rows.Add($row)
  }
  }
  $LblTitle.Text = T $mode.NameKey
  $foldersNote = ''; if ($multi) { $foldersNote = ((T 'folders_note') -f $roots.Count) }
  $LblCount.Text = ((T 'count_line') -f $nTotal, $foldersNote, (CurrentCodec).Key.ToUpper())
  $LblStatus.Text = ((T 'list_summary') -f $nNew, $nReady)
  # объём выбранного + фоновый прогноз результата (считается по таймеру, не блокируя UI)
  $sel = [long]0
  foreach ($r in $script:Rows) { if ($r.Tag -and $r.Tag.Kind -eq 'new' -and $r.IsChecked) { $sel += [long]$r.Tag.Bytes } }
  if ($sel -gt 0) { $LblSrcTotal.Text = (T 'lbl_to_process') + (HumanSize $sel) } else { $LblSrcTotal.Text = '—' }
  $LblSaved.Text = ''; $LblSaved.Foreground = $ClrTx2
  $LblEta.Text = '—'
  $script:EstBusy = $true
}

# установить выбранные папки и обновить подпись в рейле
function Set-Roots([string[]]$dirs) {
  $d = @($dirs | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique)
  if ($d.Count -eq 0) { return }
  $script:BaseDirs = $d
  $script:BaseDir = $d[0]          # первый корень — «основной» (кэш, тест-хуки)
  Update-FolderBox
}
# проставляет все надписи интерфейса на текущем языке и подсвечивает выбранный
function Apply-Language {
  $LblSecMode.Text   = T 'sec_mode'
  $LblSecCodec.Text  = T 'sec_codec'
  $LblSecAudio.Text  = T 'sec_audio'
  $LblSecVolume.Text = T 'sec_volume'
  $LblSecLeft.Text   = T 'sec_left'
  $LblMode0.Text = T 'mode_old';  $LblMode1.Text = T 'mode_cam';  $LblMode2.Text = T 'mode_arc'
  $script:ModeBtns[0].ToolTip = T 'mode_old_tip'
  $script:ModeBtns[1].ToolTip = T 'mode_cam_tip'
  $script:ModeBtns[2].ToolTip = T 'mode_arc_tip'
  $LblCodec0.Text = T 'codec_av1'; $LblCodec1.Text = T 'codec_hevc'; $LblCodec2.Text = T 'codec_dnxhr'
  $LblAudio0.Text = T 'audio_orig'; $LblAudio1.Text = T 'audio_aac'
  $BtnBrowse.Content  = T 'btn_browse'
  $BtnRefresh.Content = T 'btn_refresh'
  $BtnStart.Content   = T 'btn_start'
  $BtnStop.Content    = T 'btn_stop'
  if ($script:Paused) { $BtnPause.Content = T 'btn_resume' } else { $BtnPause.Content = T 'btn_pause' }
  $ChkSub.Content      = T 'chk_sub'
  $ChkShutdown.Content = T 'chk_shutdown'
  $ChkAuto.Content     = T 'chk_auto'
  if ($script:GoodSrc.Count -gt 0) { $BtnDelete.Content = ((T 'btn_delete_n') -f $script:GoodSrc.Count) }
  else { $BtnDelete.Content = T 'btn_delete' }
  $LblSettings.Text  = T 'settings'
  $LblLangLabel.Text = T 'lang_label'
  $BtnGear.ToolTip   = T 'gear_tip'
  if ($script:Lang -eq 'ru') { $LnkRu.Foreground = $ClrTx; $LnkEn.Foreground = $ClrTx2 }
  else                       { $LnkRu.Foreground = $ClrTx2; $LnkEn.Foreground = $ClrTx }
  Update-DeviceLabel
  # обновляем то, что уже нарисовано: список пересобираем только в покое
  if ($script:Phase -in @('idle','done')) { Refresh-FileList } else { Update-Progress }
}
function Set-Lang([string]$l) {
  if ($l -ne 'ru' -and $l -ne 'en') { return }
  if ($script:Lang -eq $l) { return }
  $script:Lang = $l
  Apply-Culture
  Save-Lang
  Apply-Language
  Log "язык интерфейса: $l"
}
# чем кодируем при текущем кодеке: NVENC или процессор (DNxHR всегда на CPU)
function Update-DeviceLabel {
  $c = CurrentCodec
  if ($c.Gpu -and $script:HasNvenc) {
    $LblDevice.Text = "NVENC · $($script:GpuName)"
    $LblDevice.ToolTip = ((T 'dev_gpu_tip') -f $script:GpuName)
  } else {
    $LblDevice.Text = (T 'dev_cpu')
    $LblDevice.ToolTip = ((T 'dev_cpu_tip') -f $c.Key.ToUpper())
  }
}
# подпись выбранной папки в рейле: короткое имя, полный путь — в подсказке
function Update-FolderBox {
  $d = @($script:BaseDirs | Where-Object { $_ })
  if ($d.Count -eq 0) { $d = @($script:BaseDir) }
  if ($d.Count -gt 1) {
    $TxtFolder.Text = ((T 'folders_multi') -f $d.Count, (($d | ForEach-Object { Split-Path $_ -Leaf }) -join ', '))
    $TxtFolder.ToolTip = ($d -join "`n")
    return
  }
  $p = [string]$d[0]
  $name = ''
  try { $name = Split-Path $p -Leaf } catch {}
  if (-not $name) { $name = $p }
  $TxtFolder.Text = $name
  $TxtFolder.ToolTip = $p
}

# ---- прогноз итогового размера ДО запуска ----
# Считается по той же формуле битрейта, что и в Prep-Item, включая все отсевы:
# пропущенный файл остаётся как есть и входит в прогноз своим исходным размером.
# Возвращает ожидаемый размер результата в байтах, либо -1 если прогноз невозможен.
function Estimate-Row($row) {
  $t = $row.Tag
  if (-not $t -or -not $t.Path) { return -1 }
  $mode = CurrentMode; $codec = CurrentCodec
  $src = [long]$t.Bytes
  if (-not $codec.Compress) { return -1 }        # DNxHR: битрейт задаёт профиль, не считаем
  if (-not (Test-Path -LiteralPath $t.Path)) { return -1 }
  $p = ProbeVideo $t.Path
  if ($p.Dur -le 0) { return -1 }
  if ($mode.Kind -eq 'cam' -and $p.Codec -eq 'hevc') { return $src }
  $px = [double]$p.W * $p.H * $p.Fps
  if ($mode.Kind -eq 'arc' -and $px -gt 0 -and $p.Bitrate -le $px * $ARC_BPP * 1.12) { return $src }
  $target = [double]$p.Bitrate * $mode.Ratio / 100.0
  if ($px -gt 0) { $lo = $px * $mode.BppMin; $hi = $px * $mode.BppMax; if ($target -lt $lo) { $target = $lo }; if ($target -gt $hi) { $target = $hi } }
  if ($target -lt $mode.Floor) { $target = $mode.Floor }
  if ($target -lt 500000) { $target = 500000 }
  if ($target -ge $p.Bitrate * 0.9) { return $src }   # выигрыш <10% — файл не трогаем
  $ai = AudioInfo $t.Path
  $it = New-Object psobject -Property @{ ACodec=$ai.Codec; AChans=$ai.Chans; AudioForce='' }
  $abr = 0.0
  if ((AudioArgs $it) -like '*copy*') { $abr = [double]$ai.Bitrate } else { if ($ai.Codec) { $abr = 256000.0 } }
  # NVENC стабильно отдаёт больше заданного -b:v (пики VBR) + накладные расходы контейнера.
  # Замер на тестовых файлах: факт превышал голый расчёт на 13–22%. Поправка только
  # к видео — скопированный звук предсказывается точно.
  $vbytes = [double]$target * $p.Dur / 8.0 * $EST_OVERHEAD
  $abytes = $abr * $p.Dur / 8.0
  return [long]($vbytes + $abytes)
}
# сброс прогноза: после смены режима/кодека/звука прежние оценки недействительны
function Reset-Estimate {
  foreach ($r in $script:Rows) { if ($r.Tag -and $r.Tag.ContainsKey('Est')) { $r.Tag.Remove('Est') } }
  $script:EstBusy = $true
}
# один тик фоновой оценки: пробируем несколько файлов и пересчитываем сумму по отмеченным
function Step-Estimate {
  if ($script:Phase -notin @('idle','done')) { return }
  $todo = @($script:Rows | Where-Object { $_.Tag -and $_.Tag.Kind -eq 'new' -and -not $_.Tag.ContainsKey('Est') })
  $n = 0
  foreach ($r in $todo) {
    if ($n -ge 3) { break }
    $r.Tag['Est'] = Estimate-Row $r
    $n++
  }
  $sel = [long]0; $est = [long]0; $cnt = 0; $known = 0; $noEst = $false
  foreach ($r in $script:Rows) {
    if (-not $r.Tag -or $r.Tag.Kind -ne 'new' -or -not $r.IsChecked) { continue }
    $sel += [long]$r.Tag.Bytes; $cnt++
    if ($r.Tag.ContainsKey('Est')) {
      $e = [long]$r.Tag['Est']
      if ($e -lt 0) { $noEst = $true } else { $est += $e; $known++ }
    }
  }
  if ($sel -gt 0) { $LblSrcTotal.Text = (T 'lbl_to_process') + (HumanSize $sel) } else { $LblSrcTotal.Text = '—' }
  $left = @($todo).Count - $n
  if ($cnt -eq 0) { $LblSaved.Text = ''; $script:EstBusy = $false; return }
  if ($noEst -and $known -eq 0) { $LblSaved.Text = (T 'lbl_forecast_na'); $LblSaved.Foreground = $ClrTx2; $script:EstBusy = $false; return }
  if ($left -gt 0) {
    $LblSaved.Text = ((T 'lbl_forecast_calc') -f $known, $cnt); $LblSaved.Foreground = $ClrTx2
    $script:EstBusy = $true; return
  }
  $script:EstBusy = $false
  if ($known -eq 0) { $LblSaved.Text = (T 'lbl_forecast_na'); $LblSaved.Foreground = $ClrTx2; return }
  # экстраполируем на файлы без оценки, чтобы цифра не была занижена
  $full = $est; if ($known -lt $cnt -and $known -gt 0) { $full = [long]($est * $cnt / $known) }
  $pct = 0; if ($sel -gt 0) { $pct = [int](100 - $full * 100.0 / $sel) }
  $LblSaved.Text = ((T 'lbl_forecast') -f (HumanSize $full), $pct)
  $LblSaved.Foreground = $ClrGreen
}

function Set-ControlsEnabled([bool]$on) {
  foreach ($b in $script:ModeBtns) { $b.IsEnabled = $on }
  foreach ($b in $script:CodecBtns) { $b.IsEnabled = $on }
  foreach ($b in $script:AudioBtns) { $b.IsEnabled = $on }
  $BtnBrowse.IsEnabled = $on; $BtnRefresh.IsEnabled = $on
  # список НЕ гасим: отключённый ListBox светлеет, да и прокрутка во время работы полезна
}

function Start-Run {
  $mode = CurrentMode
  $script:Queue.Clear(); $script:Active.Clear()
  $script:VQueue.Clear(); $script:VActive.Clear(); $script:GoodSrc = @()
  $script:DeferredPairs = @(); $script:DeferredFlushed = $false
  $script:Counts = @{ Ok=0; Skip=0; Err=0; VGood=0; VBad=0; EncTotal=0; VTotal=0; DefTotal=0 }
  $script:Paused = $false; $script:TotalSrcBytes = [long]0; $script:SavedBytes = [long]0; $script:DoneSrcBytes = [long]0
  $script:RunStart = Get-Date; $script:EtaSmooth = 0.0
  $script:RunMode = $mode; $script:RunCodec = CurrentCodec
  $script:Ready = New-Object System.Collections.Queue
  $script:CopyProc = $null; $script:CopyT = $null
  $script:MoveQueue = New-Object System.Collections.Queue
  $script:MoveProc = $null; $script:MoveT = $null
  # SSD-кэш включаем, если хоть одна папка на медленном (USB) диске. Дальше решение
  # принимается ПОФАЙЛОВО: то, что уже лежит на быстром диске, кодируется на месте.
  $script:SlowCache = @{}
  $script:UseStage = $false
  foreach ($r in (CurrentRoots)) { if (IsSlowPath $r) { $script:UseStage = $true; break } }
  if ($script:UseStage) { Log 'исходники на медленном диске — включаю SSD-кэш' }
  foreach ($row in $script:Rows) {
    $t = $row.Tag
    if ($t.Kind -eq 'pair') {
      $script:DeferredPairs += @{ Src=$t.Path; SrcRead=$t.Path; Out=$t.Out; FinalOut=$t.Out; StagedSrc=''; ExpectCodec=''; Item=$row }
      continue
    }
    if ($t.Kind -eq 'new' -and $row.IsChecked) {
      $script:Queue.Enqueue(@{ Path=$t.Path; Out=$t.Out; Item=$row })
      $script:TotalSrcBytes += [long]$t.Bytes
    } elseif ($t.Kind -eq 'new') {
      Set-ItemStatus $row (T 'st_unchecked') $ClrGray
    }
  }
  $script:Counts.EncTotal = $script:Queue.Count
  $script:Counts.DefTotal = $script:DeferredPairs.Count
  if ($script:Queue.Count -eq 0 -and $script:DeferredPairs.Count -eq 0) {
    [System.Windows.MessageBox]::Show((T 'dlg_nofiles'), 'BitShift') | Out-Null; return
  }
  Log "WPF-старт: режим «$($script:Str.ru[$mode.NameKey])», папки [$((CurrentRoots) -join '; ')], файлов $($script:Queue.Count), пар $($script:DeferredPairs.Count)"
  Set-ControlsEnabled $false
  $BtnStart.IsEnabled = $false; $BtnStop.IsEnabled = $true; $BtnDelete.IsEnabled = $false
  $BtnPause.IsEnabled = $true; $BtnPause.Content = (T 'btn_pause')
  Set-Bar 0
  KeepAwake $true
  $script:Phase = 'run'
}

function Prep-Item($t) {
  $mode = $script:RunMode; $codec = $script:RunCodec
  if (-not (Test-Path -LiteralPath $t.Path)) { $script:Counts.Skip++; Set-ItemStatus $t.Item (T 'st_gone') $ClrRed; return $null }
  $fi = Get-Item -LiteralPath $t.Path
  $p = ProbeVideo $fi.FullName
  $t.Item.Info = ('{0} {1}x{2} {3:0.##}fps {4}' -f $p.Codec, $p.W, $p.H, $p.Fps, $p.PixFmt)
  if (-not $codec.Compress) {
    $ai = AudioInfo $fi.FullName
    $t.TryHw = $false; $t.Probe = $p; $t.Target = 0; $t.ACodec = $ai.Codec; $t.AChans = $ai.Chans; $t.Size = $fi.Length; $t.Name = $fi.Name
    return $t
  }
  if ($mode.Kind -eq 'cam' -and $p.Codec -eq 'hevc') { $script:Counts.Skip++; Set-ItemStatus $t.Item (T 'skip_hevc') $ClrGray; Log "пропуск (уже HEVC): $($fi.Name)"; return $null }
  $px = [double]$p.W * $p.H * $p.Fps
  if ($mode.Kind -eq 'arc' -and $px -gt 0 -and $p.Bitrate -le $px * $ARC_BPP * 1.12) { $script:Counts.Skip++; Set-ItemStatus $t.Item (T 'skip_compact') $ClrGray; Log "пропуск (компактный): $($fi.Name)"; return $null }
  $target = [double]$p.Bitrate * $mode.Ratio / 100.0
  if ($px -gt 0) { $lo = $px * $mode.BppMin; $hi = $px * $mode.BppMax; if ($target -lt $lo) { $target = $lo }; if ($target -gt $hi) { $target = $hi } }
  if ($target -lt $mode.Floor) { $target = $mode.Floor }
  if ($target -lt 500000) { $target = 500000 }
  $target = [long]$target
  if ($target -ge $p.Bitrate * 0.9) { $script:Counts.Skip++; Set-ItemStatus $t.Item (T 'skip_gain') $ClrGray; Log "пропуск (<10%): $($fi.Name)"; return $null }
  $t.TryHw = $true
  if ($p.Codec -eq 'h264' -and $p.PixFmt -ne 'yuv420p' -and $p.PixFmt -ne 'yuvj420p') { $t.TryHw = $false }
  $ai = AudioInfo $fi.FullName
  $t.Probe = $p; $t.Target = $target; $t.ACodec = $ai.Codec; $t.AChans = $ai.Chans; $t.Size = $fi.Length; $t.Name = $fi.Name
  return $t
}

function Start-EncodeItem($t) {
  $src = $t.Path; $out = $t.Out
  if ($t.Staged) { $src = $t.Staged; $out = Join-Path (Split-Path $t.Staged -Parent) (Split-Path $t.Out -Leaf) }
  $item = New-Object psobject -Property @{
    Src=$src; OrigSrc=$t.Path; StagedSrc=$t.Staged; SrcSize=$t.Size; Name=$t.Name; Out=$out; FinalOut=$t.Out
    Probe=$t.Probe; Target=$t.Target; ACodec=$t.ACodec; AChans=$t.AChans; Codec=$script:RunCodec
    ProgFile=(Join-Path $script:TMP ([IO.Path]::GetRandomFileName() + '.progress'))
    ErrFile=(Join-Path $script:TMP ([IO.Path]::GetRandomFileName() + '.err'))
    Proc=$null; UsedHw=$true; Item=$t.Item; Pct=0; AudioForce=''
  }
  Set-ItemStatus $t.Item ((T 'st_encoding_start') -f [long]($t.Probe.Bitrate/1000), [long]($t.Target/1000)) $ClrBlue
  Log ("кодирую: {0} (hw={1}, ssd={2})" -f $t.Name, $t.TryHw, [bool]$t.Staged)
  StartEncode $item $t.TryHw
  [void]$script:Active.Add($item)
}

function StartEncode($item, [bool]$useHw) {
  $i = $item.Probe; $c = $item.Codec
  $color = ''
  foreach ($pair in @(@('-color_primaries', $i.Prim), @('-color_trc', $i.Trc), @('-colorspace', $i.Csp))) {
    $v = $pair[1]; if ($v -and $v -ne 'unknown' -and $v -ne 'N/A') { $color += ($pair[0] + ' ' + $v + ' ') }
  }
  if (-not $c.Gpu) {
    $a = "-y -nostdin -i $(Q $item.Src) -map_metadata 0 -c:v dnxhd -profile:v $($c.Profile) -pix_fmt yuv422p10le $color$(AudioArgs $item)-progress $(Q $item.ProgFile) -v warning $(Q $item.Out)"
    $item.Proc = Start-Process -FilePath 'ffmpeg' -ArgumentList $a -WindowStyle Hidden -PassThru -RedirectStandardError $item.ErrFile
    $null = $item.Proc.Handle; $item.UsedHw = $false; return
  }
  $hw = ''
  if ($useHw) {
    $hw = '-hwaccel cuda '
    if (($i.Codec -eq 'h264' -or $i.Codec -eq 'hevc') -and $i.PixFmt -notlike '*10*') { $hw += '-hwaccel_output_format cuda ' }
  }
  $extra = ''
  if ($i.PixFmt -like '*10*') { if ($c.Key -eq 'hevc') { $extra += '-profile:v main10 -pix_fmt p010le ' } else { $extra += '-pix_fmt p010le ' } }
  $tag = ''; if ($c.Tag) { $tag = "-tag:v $($c.Tag) " }
  $audio = AudioArgs $item
  $a = "-y -nostdin $hw-i $(Q $item.Src) -map_metadata 0 -c:v $($c.Enc) -preset $PRESET -b:v $($item.Target) $tag$extra$color$audio-progress $(Q $item.ProgFile) -v warning $(Q $item.Out)"
  $item.Proc = Start-Process -FilePath 'ffmpeg' -ArgumentList $a -WindowStyle Hidden -PassThru -RedirectStandardError $item.ErrFile
  $null = $item.Proc.Handle; $item.UsedHw = $useHw
}

function Step-Encode {
  if ($script:UseStage) {
    if ($script:CopyProc -and $script:CopyProc.HasExited) {
      $ec = $script:CopyProc.ExitCode
      if ($ec -lt 8 -and (Test-Path -LiteralPath $script:CopyT.Staged)) { Set-ItemStatus $script:CopyT.Item (T 'st_on_ssd') $null; $script:Ready.Enqueue($script:CopyT) }
      else { $script:Counts.Err++; Set-ItemStatus $script:CopyT.Item ((T 'st_copy_fail') -f $ec) $ClrRed; Log "ошибка robocopy ($ec): $($script:CopyT.Path)" }
      $script:CopyProc = $null; $script:CopyT = $null
    }
    # живой прогресс копирования на SSD — по размеру растущего файла
    if ($script:CopyProc -and $script:CopyT) {
      Set-RowBar $script:CopyT.Item (CopyPct $script:CopyT.Staged $script:CopyT.Size) $ClrTx2
    }
    if (-not $script:CopyProc -and -not $script:Paused) {
      while ($script:Queue.Count -gt 0 -and $script:Ready.Count -lt 2) {
        $t = Prep-Item $script:Queue.Dequeue(); if (-not $t) { continue }
        # файл уже на быстром диске (внутренний SSD) — копировать никуда не надо,
        # кодируем прямо на месте. Кэш нужен только для медленных USB-источников.
        if (-not (IsSlowPath $t.Path)) {
          $t.Staged = ''; Set-ItemStatus $t.Item (T 'st_fast_disk') $null
          $script:Ready.Enqueue($t); continue
        }
        $free = 0; try { $free = (Get-PSDrive -Name $script:TMP.Substring(0,1)).Free } catch {}
        if ($free -lt ($t.Size * 1.5 + 10GB)) { $t.Staged = ''; Set-ItemStatus $t.Item (T 'st_low_space') $null; $script:Ready.Enqueue($t); continue }
        # уникальная подпапка на каждый файл: в дереве бывают одинаковые basename в
        # разных папках (камера сбрасывает нумерацию), а плоский %TEMP% их сталкивал —
        # два ffmpeg писали в один C0008_v2.mp4 → гонки, «файла нет», сбои переноса
        $t.StageDir = Join-Path $script:TMP ([IO.Path]::GetRandomFileName())
        New-Item -ItemType Directory -Path $t.StageDir -Force | Out-Null
        $t.Staged = Join-Path $t.StageDir $t.Name
        Set-ItemStatus $t.Item (T 'st_copying') $ClrBlue
        $script:CopyProc = StartRobocopy (Split-Path $t.Path -Parent) $t.StageDir $t.Name $false; $script:CopyT = $t; break
      }
    }
    while ($script:Active.Count -lt $JOBS -and $script:Ready.Count -gt 0 -and -not $script:Paused) { Start-EncodeItem $script:Ready.Dequeue() }
  } else {
    while ($script:Active.Count -lt $JOBS -and $script:Queue.Count -gt 0 -and -not $script:Paused) {
      $t = Prep-Item $script:Queue.Dequeue(); if (-not $t) { continue }
      $t.Staged = ''; Start-EncodeItem $t
    }
  }
  foreach ($item in @($script:Active)) {
    if (-not $item.Proc.HasExited) {
      $pp = ProgPct $item.ProgFile $item.Probe.Dur
      if ($pp -ge 0) {
        $pc = [int]$pp
        Set-ItemStatus $item.Item ((T 'st_encoding') -f $pc) $ClrBlue; $item.Pct = $pc
        Set-RowBar $item.Item $pp $ClrBlue
      }
      continue
    }
    $code = $item.Proc.ExitCode
    if ($code -ne 0 -and $item.UsedHw) {
      Remove-Item -LiteralPath $item.Out -ErrorAction SilentlyContinue
      Set-ItemStatus $item.Item (T 'st_hw_retry') $ClrBlue; Log "повтор на CPU: $($item.Name)"
      StartEncode $item $false; continue
    }
    # экзотический звук может не лечь в контейнер результата — тогда один раз
    # пробуем пережать его в AAC, вместо того чтобы терять весь файл
    if ($code -ne 0 -and -not $item.AudioForce -and (AudioArgs $item) -like '*copy*') {
      Remove-Item -LiteralPath $item.Out -ErrorAction SilentlyContinue
      $item.AudioForce = 'aac'
      Set-ItemStatus $item.Item (T 'st_audio_retry') $ClrBlue; Log "повтор с AAC-звуком: $($item.Name)"
      StartEncode $item $item.UsedHw; continue
    }
    [void]$script:Active.Remove($item)
    if ($code -eq 0) {
      $dsz = 0
      try { $si = Get-Item -LiteralPath $item.OrigSrc; $di = Get-Item -LiteralPath $item.Out; $di.CreationTime = $si.CreationTime; $di.LastWriteTime = $si.LastWriteTime; $dsz = $di.Length } catch {}
      $saved = ''; if ($item.SrcSize -gt 0 -and $dsz -gt 0) { $saved = (' · −{0}%' -f [int](100 - $dsz * 100 / $item.SrcSize)) }
      if ($item.SrcSize -gt 0 -and $dsz -gt 0) { $script:DoneSrcBytes += [long]$item.SrcSize; $script:SavedBytes += ([long]$item.SrcSize - [long]$dsz) }
      # инфо о финальном файле: кодек · размер · сжатие (остаётся видимым и после проверки)
      $item.Item.Info = ('→ {0} · {1}{2}' -f $item.Codec.OutCodec, (HumanSize $dsz), $saved)
      $script:Counts.Ok++
      Set-ItemStatus $item.Item (T 'st_done') $ClrGreen; Set-RowBar $item.Item 100 $ClrGreen
      $vsrc = $item.OrigSrc; if ($item.StagedSrc) { $vsrc = $item.StagedSrc }
      $script:VQueue.Enqueue(@{ Src=$item.OrigSrc; SrcRead=$vsrc; Out=$item.Out; FinalOut=$item.FinalOut; StagedSrc=$item.StagedSrc; ExpectCodec=$item.Codec.OutCodec; Item=$item.Item })
      $script:Counts.VTotal++
      Log "OK: $(Split-Path $item.Out -Leaf)"
    } else {
      Remove-Item -LiteralPath $item.Out -ErrorAction SilentlyContinue
      if ($item.StagedSrc) { Remove-Item -LiteralPath $item.StagedSrc -Force -ErrorAction SilentlyContinue }
      $script:Counts.Err++
      $err = ErrSummary $item.ErrFile
      Set-ItemStatus $item.Item ((T 'st_error') + $err) $ClrRed; Set-RowBar $item.Item -1 $null; Log "ОШИБКА: $($item.Name) $err"
    }
  }
}

function VerifyBad($t, [string]$why) {
  $script:Counts.VBad++
  # результат бракован — откатываем учтённую при кодировании экономию (оригинал остаётся,
  # результат удаляется). Только для файлов этого запуска: у отложенных пар ExpectCodec пуст.
  if ($t.ExpectCodec) {
    try {
      $rb = [long]0; if (Test-Path -LiteralPath $t.Out) { $rb = (Get-Item -LiteralPath $t.Out).Length }
      $sb = [long]0; if (Test-Path -LiteralPath $t.Src) { $sb = (Get-Item -LiteralPath $t.Src).Length }
      if ($sb -gt 0) { $script:DoneSrcBytes -= $sb; if ($rb -gt 0) { $script:SavedBytes -= ($sb - $rb) } }
    } catch {}
  }
  if ($t.StagedSrc) { Remove-Item -LiteralPath $t.StagedSrc -Force -ErrorAction SilentlyContinue }
  if ($t.Out -ne $t.FinalOut) { Remove-Item -LiteralPath $t.Out -Force -ErrorAction SilentlyContinue }
  Set-ItemStatus $t.Item ((T 'st_fail') -f $why) $ClrRed
  Log "проверка $(Split-Path $t.Out -Leaf): ПРОВАЛ ($why)"
}

function Step-Verify {
  $vlim = if (Encoding-Active) { $VJOBS_OVERLAP } else { $VJOBS }
  while ($script:VActive.Count -lt $vlim -and $script:VQueue.Count -gt 0) {
    $t = $script:VQueue.Dequeue()
    Set-ItemStatus $t.Item 'проверяю…' $ClrBlue
    $bad = ''
    if (-not (Test-Path -LiteralPath $t.Out) -or (Get-Item -LiteralPath $t.Out).Length -eq 0) { $bad = (T 'bad_nofile') }
    if (-not $bad) {
      $dp = ProbeVideo $t.Out; $sp = ProbeVideo $t.SrcRead
      $okCodec = if ($t.ExpectCodec) { $dp.Codec -eq $t.ExpectCodec } else { @('hevc','av1','dnxhd') -contains $dp.Codec }
      if (-not $okCodec) { $bad = ((T 'bad_codec') -f $dp.Codec) }
      elseif ($sp.Dur -le 0 -or $dp.Dur -le 0) { $bad = (T 'bad_noduration') }
      else { $tol = [math]::Max($sp.Dur * 0.02, 2.0); if ([math]::Abs($sp.Dur - $dp.Dur) -gt $tol) { $bad = (T 'bad_duration') } }
    }
    if (-not $bad -and $t.Src -match '\.(mp4|mov)$') {
      $p1 = PacketCount $t.SrcRead; $p2 = PacketCount $t.Out
      if ($p1 -ge 0 -and $p2 -ge 0 -and [math]::Abs($p1 - $p2) -gt 2) { $bad = ((T 'bad_frames') -f $p1, $p2) }
    }
    if ($bad) { VerifyBad $t $bad; continue }
    $t.ErrFile = Join-Path $script:TMP ([IO.Path]::GetRandomFileName() + '.verr')
    $t.VProg = Join-Path $script:TMP ([IO.Path]::GetRandomFileName() + '.vprogress')
    $t.Dur = $dp.Dur                      # длительность результата — для шкалы проверки
    $t.Stage = 'hw'
    Set-RowBar $t.Item 0 $ClrViolet
    $a = "-nostdin -v error -hwaccel cuda -i $(Q $t.Out) -progress $(Q $t.VProg) -f null -"
    $t.Proc = Start-Process -FilePath 'ffmpeg' -ArgumentList $a -WindowStyle Hidden -PassThru -RedirectStandardError $t.ErrFile
    $null = $t.Proc.Handle
    [void]$script:VActive.Add($t)
  }
  foreach ($t in @($script:VActive)) {
    if (-not $t.Proc.HasExited) {
      $vp = ProgPct $t.VProg $t.Dur
      if ($vp -ge 0) { Set-ItemStatus $t.Item ((T 'st_verifying') -f [int]$vp) $ClrViolet; Set-RowBar $t.Item $vp $ClrViolet }
      continue
    }
    $hadErrors = $false; try { $hadErrors = ((Get-Item -LiteralPath $t.ErrFile -ErrorAction SilentlyContinue).Length -gt 0) } catch {}
    if (($t.Proc.ExitCode -ne 0 -or $hadErrors) -and $t.Stage -eq 'hw') {
      $t.Stage = 'sw'
      Remove-Item -LiteralPath $t.VProg -Force -ErrorAction SilentlyContinue
      Set-RowBar $t.Item 0 $ClrViolet
      $a = "-nostdin -v error -i $(Q $t.Out) -progress $(Q $t.VProg) -f null -"
      $t.Proc = Start-Process -FilePath 'ffmpeg' -ArgumentList $a -WindowStyle Hidden -PassThru -RedirectStandardError $t.ErrFile
      $null = $t.Proc.Handle; continue
    }
    [void]$script:VActive.Remove($t)
    if ($t.Proc.ExitCode -eq 0 -and -not $hadErrors) {
      $script:Counts.VGood++
      if ($t.StagedSrc) { Remove-Item -LiteralPath $t.StagedSrc -Force -ErrorAction SilentlyContinue }
      if ($t.Out -ne $t.FinalOut) { Set-ItemStatus $t.Item (T 'st_verified_wait_move') $ClrBlue; Set-RowBar $t.Item 0 $ClrTx2; $script:MoveQueue.Enqueue($t) }
      else { $script:GoodSrc += @{ Src=$t.Src; Item=$t.Item }; Set-ItemStatus $t.Item (T 'st_verified') $ClrGreen; Set-RowBar $t.Item 100 $ClrGreen }
      Log "проверка $(Split-Path $t.Out -Leaf): ок"
    } else { VerifyBad $t (T 'bad_decode') }
  }
}

function Step-Move {
  if (Encoding-Active) { return }
  if ($script:MoveProc) {
    if (-not $script:MoveProc.HasExited) {
      # живой прогресс переноса — по размеру растущего файла назначения
      if ($script:MoveT) { Set-RowBar $script:MoveT.Item (CopyPct $script:MoveT.FinalOut $script:MoveT.OutLen) $ClrTx2 }
      return
    }
    $t = $script:MoveT; $ec = $script:MoveProc.ExitCode
    $script:MoveProc = $null; $script:MoveT = $null
    if ($ec -lt 8 -and (Test-Path -LiteralPath $t.FinalOut)) {
      try { $si = Get-Item -LiteralPath $t.Src; $di = Get-Item -LiteralPath $t.FinalOut; $di.CreationTime = $si.CreationTime; $di.LastWriteTime = $si.LastWriteTime } catch {}
      $script:GoodSrc += @{ Src=$t.Src; Item=$t.Item }
      Set-ItemStatus $t.Item (T 'st_verified_moved') $ClrGreen; Set-RowBar $t.Item 100 $ClrGreen
      Log "перенесён: $(Split-Path $t.FinalOut -Leaf)"
    } else { Set-ItemStatus $t.Item ((T 'st_move_fail') -f $ec) $ClrRed; Set-RowBar $t.Item -1 $null; Log "ошибка переноса ($ec): $($t.FinalOut)" }
  }
  if (-not $script:MoveProc -and $script:MoveQueue.Count -gt 0) {
    $t = $script:MoveQueue.Dequeue()
    Set-ItemStatus $t.Item (T 'st_moving') $ClrBlue
    $t.OutLen = 0; try { $t.OutLen = (Get-Item -LiteralPath $t.Out).Length } catch {}
    Set-RowBar $t.Item 0 $ClrTx2
    $script:MoveProc = StartRobocopy (Split-Path $t.Out -Parent) (Split-Path $t.FinalOut -Parent) (Split-Path $t.Out -Leaf) $true
    $script:MoveT = $t
  }
}

# $natural = конвейер дошёл до конца сам. При остановке кнопкой «Стоп» = $false:
# пользователь за компьютером, выключать его нельзя.
function Finish-Run([bool]$natural = $true) {
  $script:Phase = 'done'; KeepAwake $false
  Set-ControlsEnabled $true
  $BtnStart.IsEnabled = $true; $BtnStop.IsEnabled = $false
  $script:Paused = $false; $BtnPause.IsEnabled = $false; $BtnPause.Content = (T 'btn_pause')
  Set-Bar 1
  Update-Stats
  Update-Eta
  $c = $script:Counts
  $LblStatus.Text = ((T 'finish') -f $c.Ok, $c.Skip, $c.Err, $c.VGood, $c.VTotal)
  Log "WPF-конец: ok=$($c.Ok) skip=$($c.Skip) err=$($c.Err) vgood=$($c.VGood) vbad=$($c.VBad)"
  if ($script:GoodSrc.Count -gt 0) {
    $BtnDelete.Content = ((T 'btn_delete_n') -f $script:GoodSrc.Count); $BtnDelete.IsEnabled = $true
    # автоудаление (если включена галочка): в Корзину идут только проверенные,
    # провалившие проверку исходники не трогаются (они не попали в GoodSrc)
    if ($ChkAuto.IsChecked -eq $true) { Log 'автоудаление включено'; Recycle-Good 'авто' }
  }
  # автовыключение ПК: только при естественном завершении, с отсрочкой (успеть отменить),
  # и никогда в тест-режиме
  if ($natural -and $ChkShutdown.IsChecked -eq $true -and $env:HEVC_WPF_TEST -ne '1') {
    $secs = 120
    $LblStatus.Text = "$($LblStatus.Text)  •  " + ((T 'shutdown_note') -f $secs)
    Log "автовыключение ПК: shutdown через $secs с"
    try {
      Start-Process -FilePath 'shutdown' -ArgumentList ('/s /t ' + $secs + ' /c "' + (T 'shutdown_reason') + '"') -WindowStyle Hidden
    } catch { Log "не смог запустить shutdown: $_" }
  }
}

function Stop-Run {
  if ($script:Paused) {
    foreach ($item in $script:Active) { try { if ($item.Proc -and -not $item.Proc.HasExited) { [HevcWpf.ProcCtl]::NtResumeProcess($item.Proc.Handle) | Out-Null } } catch {} }
    $script:Paused = $false
  }
  foreach ($item in $script:Active) {
    try { if ($item.Proc -and -not $item.Proc.HasExited) { $item.Proc.Kill() } } catch {}
    Remove-Item -LiteralPath $item.Out -ErrorAction SilentlyContinue
    if ($item.StagedSrc) { Remove-Item -LiteralPath $item.StagedSrc -Force -ErrorAction SilentlyContinue }
    Set-ItemStatus $item.Item (T 'st_stopped') $ClrGray
  }
  $script:Active.Clear()
  foreach ($t in $script:VActive) { try { if ($t.Proc -and -not $t.Proc.HasExited) { $t.Proc.Kill() } } catch {} }
  $script:VActive.Clear()
  foreach ($p in @($script:CopyProc, $script:MoveProc)) { try { if ($p -and -not $p.HasExited) { $p.Kill() } } catch {} }
  if ($script:CopyT) { Remove-Item -LiteralPath $script:CopyT.Staged -Force -ErrorAction SilentlyContinue }
  $script:CopyProc = $null; $script:CopyT = $null; $script:MoveProc = $null; $script:MoveT = $null
  foreach ($t in @($script:Ready)) { if ($t.Staged) { Remove-Item -LiteralPath $t.Staged -Force -ErrorAction SilentlyContinue } }
  $script:Ready.Clear(); $script:MoveQueue.Clear(); $script:Queue.Clear(); $script:VQueue.Clear()
  $script:DeferredPairs = @(); $script:DeferredFlushed = $true
  Log 'WPF: остановлено пользователем'
  Finish-Run $false
  $LblStatus.Text = (T 'stopped_hint')
}

# пауза/продолжение кодирования: приостанавливаем сами процессы ffmpeg (NVENC замирает),
# новые не запускаем. Проверка уже готовых файлов при этом продолжает дренироваться.
function Toggle-Pause {
  if ($script:Phase -ne 'run') { return }
  $script:Paused = -not $script:Paused
  if ($script:Paused) {
    foreach ($item in $script:Active) { try { if ($item.Proc -and -not $item.Proc.HasExited) { [HevcWpf.ProcCtl]::NtSuspendProcess($item.Proc.Handle) | Out-Null } } catch {} }
    $BtnPause.Content = (T 'btn_resume'); Log 'пауза: кодирование приостановлено'
  } else {
    foreach ($item in $script:Active) { try { if ($item.Proc -and -not $item.Proc.HasExited) { [HevcWpf.ProcCtl]::NtResumeProcess($item.Proc.Handle) | Out-Null } } catch {} }
    $BtnPause.Content = (T 'btn_pause'); Log 'пауза снята — продолжаю'
  }
}

# само удаление проверенных исходников В КОРЗИНУ (никогда безвозвратно).
# Трогаются только файлы из GoodSrc — те, чей результат ПОЛНОСТЬЮ прошёл проверку.
function Recycle-Good([string]$how) {
  $n = $script:GoodSrc.Count; if ($n -eq 0) { return }
  Add-Type -AssemblyName Microsoft.VisualBasic
  $trashed = 0; $failed = 0
  foreach ($g in $script:GoodSrc) {
    try {
      [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($g.Src, [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)
      $trashed++; Set-ItemStatus $g.Item (T 'st_in_trash') $ClrGreen; Log "в корзину ($how): $(Split-Path $g.Src -Leaf)"
    } catch { $failed++; Set-ItemStatus $g.Item (T 'st_not_deleted') $ClrRed; Log "НЕ удалился: $(Split-Path $g.Src -Leaf)" }
  }
  $script:GoodSrc = @(); $BtnDelete.IsEnabled = $false
  $LblStatus.Text = ((T 'trash_result') -f $trashed, $failed); Log "удаление ($how): $trashed в корзину, $failed проблем"
}
# ручное удаление — с подтверждением
function Delete-Originals {
  $n = $script:GoodSrc.Count; if ($n -eq 0) { return }
  $r = [System.Windows.MessageBox]::Show(((T 'dlg_confirm') -f $n), 'BitShift', [System.Windows.MessageBoxButton]::YesNo, [System.Windows.MessageBoxImage]::Question)
  if ($r -ne [System.Windows.MessageBoxResult]::Yes) { Log 'удаление: отказ'; return }
  Recycle-Good 'вручную'
}

function Encoding-Active {
  return ($script:Queue.Count -gt 0 -or $script:Active.Count -gt 0 -or $script:Ready.Count -gt 0 -or [bool]$script:CopyProc)
}
# общий процент по всему пути: каждый файл = 1 единица (кодирование 0.5 + проверка 0.5;
# пропуск/ошибка кодирования — терминальны сразу; отложенные пары — только проверка).
function Overall-Fraction {
  $total = $script:Counts.EncTotal + $script:Counts.DefTotal
  if ($total -le 0) { return @{ Pct=0; Units=0.0; Total=0 } }
  $verified = $script:Counts.VGood + $script:Counts.VBad
  $encWaiting = $script:Counts.VTotal - $verified; if ($encWaiting -lt 0) { $encWaiting = 0 }
  $term = $script:Counts.Skip + $script:Counts.Err
  $activePartial = 0.0; foreach ($it in $script:Active) { $activePartial += [double]$it.Pct / 100.0 }
  $units = $verified + $term + ($encWaiting * 0.5) + ($activePartial * 0.5)
  if ($units -gt $total) { $units = $total }
  return @{ Pct=[int]($units * 100.0 / $total); Units=$units; Total=$total }
}
function HumanTime([double]$sec) {
  if ($sec -lt 45) { return (T 't_lessmin') }
  $m = [int][math]::Round($sec / 60.0)
  if ($m -lt 60) { return ((T 't_min') -f $m) }
  $h = [int][math]::Floor($m / 60); $mm = $m % 60
  if ($h -lt 24) { if ($mm -eq 0) { return ((T 't_hour') -f $h) } else { return ((T 't_hourmin') -f $h, $mm) } }
  $d = [int][math]::Floor($h / 24); $hh = $h % 24
  return ((T 't_day') -f $d, $hh)
}
# Оценка по БАЙТАМ, а не по числу файлов: у него в архиве и 100 МБ, и 9 ГБ в одной
# папке, счёт по штукам врал бы в разы. Замеряем фактическую пропускную способность
# всего конвейера (кодирование+проверка+перенос идут внахлёст, так что она уже
# учитывает все стадии) и экстраполируем на остаток. Сглаживаем, чтобы не прыгало.
function Update-Eta {
  if ($script:Phase -ne 'run' -or $script:TotalSrcBytes -le 0 -or -not $script:RunStart) {
    $script:EtaSmooth = 0.0; $LblEta.Text = '—'; return
  }
  $doneB = [double]$script:DoneSrcBytes
  foreach ($it in $script:Active) { if ($it.SrcSize -gt 0) { $doneB += [double]$it.SrcSize * ([double]$it.Pct / 100.0) } }
  $elapsed = ((Get-Date) - $script:RunStart).TotalSeconds
  if ($elapsed -lt 20 -or $doneB -le 0) { $LblEta.Text = (T 't_calc'); return }
  $frac = $doneB / [double]$script:TotalSrcBytes
  if ($frac -ge 0.999) { $LblEta.Text = (T 't_finishing'); return }
  $rem = $elapsed * (1.0 - $frac) / $frac
  # хвост: файлы, которые уже закодированы, но ещё ждут проверки/переноса
  $tail = $script:VQueue.Count + $script:VActive.Count + $script:MoveQueue.Count
  if (-not (Encoding-Active) -and $tail -gt 0 -and $rem -lt 20) { $rem = 20 }
  if ($script:EtaSmooth -le 0) { $script:EtaSmooth = $rem } else { $script:EtaSmooth = $script:EtaSmooth * 0.75 + $rem * 0.25 }
  $LblEta.Text = HumanTime $script:EtaSmooth
}
function Update-Stats {
  if ($script:TotalSrcBytes -gt 0) { $LblSrcTotal.Text = (T 'lbl_src_total') + (HumanSize $script:TotalSrcBytes) }
  else { $LblSrcTotal.Text = '—' }
  if ($script:DoneSrcBytes -gt 0 -and $script:SavedBytes -gt 0) {
    $pct = [int]($script:SavedBytes * 100.0 / $script:DoneSrcBytes)
    $LblSaved.Text = ((T 'lbl_saved') -f (HumanSize $script:SavedBytes), $pct)
    $LblSaved.Foreground = $ClrGreen
  } else { $LblSaved.Text = (T 'lbl_saved_none'); $LblSaved.Foreground = $ClrTx2 }
}
# своя шкала: ширину заливки считаем сами от фактической ширины трека (нативный
# индикатор ProgressBar в этом окне отрисовывался ненадёжно)
function Set-Bar([double]$frac) {
  if ($frac -lt 0) { $frac = 0 }; if ($frac -gt 1) { $frac = 1 }
  $w = 0.0; try { $w = [double]$BarTrack.ActualWidth } catch {}
  if ($w -le 0) { $w = 500.0 }
  $BarFill.Width = [math]::Round($w * $frac)
}
function Update-Progress {
  $ov = Overall-Fraction
  $frac = 0.0; if ($ov.Total -gt 0) { $frac = $ov.Units / $ov.Total }
  Set-Bar $frac
  $parts = @()
  if ($script:Paused) { $parts += (T 'run_paused') }
  if ($script:Counts.EncTotal -gt 0) { $ed = $script:Counts.Ok + $script:Counts.Skip + $script:Counts.Err; $parts += ((T 'run_encoding') -f $ed, $script:Counts.EncTotal, $script:Active.Count) }
  $vt = ''; if ($script:Counts.VTotal -gt 0) { $vt = "/$($script:Counts.VTotal)" }
  $parts += ((T 'run_verified') -f $script:Counts.VGood, $vt)
  if ($script:Counts.VBad -gt 0) { $parts += ((T 'run_failed') -f $script:Counts.VBad) }
  if ($script:MoveQueue.Count -gt 0 -or $script:MoveProc) { $parts += (T 'run_moving') }
  $LblStatus.Text = ('{0}%   •   {1}' -f $ov.Pct, ($parts -join '   •   '))
  Update-Stats
  Update-Eta
}
function Step-Pipeline {
  Step-Encode
  if (-not (Encoding-Active) -and -not $script:DeferredFlushed) {
    foreach ($pr in $script:DeferredPairs) { $script:VQueue.Enqueue($pr); $script:Counts.VTotal++ }
    $script:DeferredPairs = @(); $script:DeferredFlushed = $true
  }
  Step-Verify
  Step-Move
  Update-Progress
  if (-not (Encoding-Active) -and $script:DeferredFlushed -and $script:VQueue.Count -eq 0 -and $script:VActive.Count -eq 0 -and $script:MoveQueue.Count -eq 0 -and -not $script:MoveProc) { Finish-Run }
}

# состояние конвейера
$script:Queue = New-Object System.Collections.Queue
$script:Active = New-Object System.Collections.ArrayList
$script:VQueue = New-Object System.Collections.Queue
$script:VActive = New-Object System.Collections.ArrayList
$script:GoodSrc = @()
$script:Counts = @{ Ok=0; Skip=0; Err=0; VGood=0; VBad=0; EncTotal=0; VTotal=0; DefTotal=0 }
$script:Paused = $false
$script:TotalSrcBytes = [long]0; $script:SavedBytes = [long]0; $script:DoneSrcBytes = [long]0
$script:RunStart = $null; $script:EtaSmooth = 0.0

# события выбора режима/кодека
for ($i = 0; $i -lt 3; $i++) {
  $script:ModeBtns[$i].Tag = $i
  $script:ModeBtns[$i].Add_Checked({ param($s,$e) if ($script:Phase -in @('idle','done')) { $script:ModeSel = [int]$s.Tag; Refresh-FileList } })
}
for ($i = 0; $i -lt 3; $i++) {
  $script:CodecBtns[$i].Tag = $i
  $script:CodecBtns[$i].Add_Checked({ param($s,$e) if ($script:Phase -in @('idle','done')) { $script:CodecSel = [int]$s.Tag; Update-DeviceLabel; Refresh-FileList } })
}
for ($i = 0; $i -lt 2; $i++) {
  $script:AudioBtns[$i].Tag = $i
  $script:AudioBtns[$i].Add_Checked({ param($s,$e) if ($script:Phase -in @('idle','done')) { $script:AudioSel = [int]$s.Tag; Reset-Estimate } })
}
$BtnRefresh.Add_Click({ Refresh-FileList })
$ChkSub.Add_Click({ if ($script:Phase -in @('idle','done')) { Refresh-FileList } })
function Browse-Folders {
  if ($script:Phase -notin @('idle','done')) { return }
  $picked = @()
  # системный диалог с мультивыбором (Ctrl/Shift). Если COM почему-то недоступен —
  # откатываемся на обычный выбор одной папки.
  if ('MultiFolderPicker' -as [type]) {
    try { $picked = @([MultiFolderPicker]::Pick((T 'dlg_browse_multi'), $script:BaseDir)) }
    catch { Log "мультивыбор папок не сработал: $_"; $picked = @() }
  }
  if ($picked.Count -eq 0 -and -not ('MultiFolderPicker' -as [type])) {
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = (T 'dlg_browse')
    $dlg.SelectedPath = $script:BaseDir
    if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $picked = @($dlg.SelectedPath) }
  }
  if ($picked.Count -gt 0) { Set-Roots $picked; Refresh-FileList }
}
$BtnBrowse.Add_Click({ Browse-Folders })
$PopSettings.PlacementTarget = $BtnGear
$BtnGear.Add_MouseLeftButtonUp({ $PopSettings.IsOpen = -not $PopSettings.IsOpen })
$BtnGear.Add_MouseEnter({ $BtnGear.Background = (Br '#1EFFFFFF'); $GearTeeth.Fill = $ClrTx })
$BtnGear.Add_MouseLeave({ $BtnGear.Background = [System.Windows.Media.Brushes]::Transparent; $GearTeeth.Fill = $ClrTx2 })
$LnkRu.Add_MouseLeftButtonUp({ Set-Lang 'ru' })
$LnkEn.Add_MouseLeftButtonUp({ Set-Lang 'en' })
$BtnStart.Add_Click({ Start-Run })
$BtnPause.Add_Click({ Toggle-Pause })
$BtnStop.Add_Click({ Stop-Run })
$BtnDelete.Add_Click({ Delete-Originals })

$Timer = New-Object System.Windows.Threading.DispatcherTimer
$Timer.Interval = [TimeSpan]::FromMilliseconds(400)
$Timer.Add_Tick({
  if ($script:Phase -eq 'run') { try { Step-Pipeline } catch { Log "ошибка конвейера: $_"; $LblStatus.Text = "Ошибка: $_" } }
  else { try { Step-Estimate } catch { Log "ошибка прогноза: $_" } }
})
$Timer.Start()

$Window.Add_Closing({ param($s, $e)
  if ($script:Phase -eq 'run') {
    $r = [System.Windows.MessageBox]::Show((T 'dlg_closing'), 'BitShift', [System.Windows.MessageBoxButton]::YesNo, [System.Windows.MessageBoxImage]::Question)
    if ($r -ne [System.Windows.MessageBoxResult]::Yes) { $e.Cancel = $true; return }
    Stop-Run
  }
  KeepAwake $false
  Remove-Item -LiteralPath $script:TMP -Recurse -Force -ErrorAction SilentlyContinue
})

$Window.Add_SourceInitialized({
  try {
    $h = (New-Object System.Windows.Interop.WindowInteropHelper $Window).Handle
    $rnd = 2; [HevcWpf.Dwm]::DwmSetWindowAttribute($h, 33, [ref]$rnd, 4) | Out-Null   # скруглить углы окна (Win11)
  } catch {}
})

Update-FolderBox
Apply-Language

if ($env:HEVC_WPF_TEST -ne '1') {
  $Window.ShowDialog() | Out-Null
}
