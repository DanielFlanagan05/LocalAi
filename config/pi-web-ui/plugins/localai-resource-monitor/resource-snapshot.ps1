$ErrorActionPreference = 'Stop'

# Resolve the adapter on every sample. Windows can change LUIDs after a reboot.
# DXGI reports the real 64-bit dedicated memory size; WMI AdapterRAM is not used.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class LocalAiDxgi {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct Desc {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string Description;
    public uint VendorId, DeviceId, SubSysId, Revision;
    public UIntPtr DedicatedVideoMemory, DedicatedSystemMemory, SharedSystemMemory;
    public uint LuidLow; public int LuidHigh; public uint Flags;
  }
  [DllImport("dxgi.dll")] static extern int CreateDXGIFactory1(ref Guid iid, out IntPtr factory);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int EnumAdapter(IntPtr self, uint index, out IntPtr adapter);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetDesc(IntPtr self, out Desc desc);
  static T Method<T>(IntPtr obj, int index) where T:class {
    return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj),index*IntPtr.Size),typeof(T)) as T;
  }
  public static Desc FindRadeon() {
    Guid iid=new Guid("770aae78-f26f-4dba-a829-253c83d1b387");
    IntPtr factory; Marshal.ThrowExceptionForHR(CreateDXGIFactory1(ref iid,out factory));
    try {
      var enumerate=Method<EnumAdapter>(factory,12);
      for(uint i=0;;i++) {
        IntPtr adapter; int hr=enumerate(factory,i,out adapter);
        if(hr==unchecked((int)0x887a0002)) break;
        Marshal.ThrowExceptionForHR(hr);
        try {
          Desc d; Marshal.ThrowExceptionForHR(Method<GetDesc>(adapter,10)(adapter,out d));
          if(d.VendorId==0x1002 && d.DeviceId==0x744c && d.Description.Contains("7900 XT")) return d;
        } finally { Marshal.Release(adapter); }
      }
      throw new InvalidOperationException("RX 7900 XT not found via DXGI; refusing to guess an adapter.");
    } finally { Marshal.Release(factory); }
  }
}
'@
$adapter = [LocalAiDxgi]::FindRadeon()
$high = [BitConverter]::ToUInt32([BitConverter]::GetBytes($adapter.LuidHigh),0)
$luidPrefix = ('luid_0x{0:x8}_0x{1:x8}_phys_' -f $high,$adapter.LuidLow)
$counterPaths = @(
    '\GPU Adapter Memory(*)\Dedicated Usage',
    '\GPU Adapter Memory(*)\Total Committed',
    '\GPU Engine(*)\Utilization Percentage'
)
$samples = @(Get-Counter -Counter $counterPaths -ErrorAction Stop | ForEach-Object { $_.CounterSamples })
$rxSamples = @($samples | Where-Object { $_.InstanceName.ToLowerInvariant().Contains($luidPrefix) })
$dedicated = @($rxSamples | Where-Object { $_.Path -match '\\dedicated usage$' })
$committed = @($rxSamples | Where-Object { $_.Path -match '\\total committed$' })
$engines = @($rxSamples | Where-Object { $_.Path -match '\\utilization percentage$' })
if ($dedicated.Count -eq 0 -or $committed.Count -eq 0) {
    throw "RX 7900 XT GPU memory counters were not found for $luidPrefix"
}
$dedicatedBytes = [double](($dedicated | Measure-Object -Property CookedValue -Sum).Sum)
$committedBytes = [double](($committed | Measure-Object -Property CookedValue -Sum).Sum)
$totalBytes = [double]$adapter.DedicatedVideoMemory.ToUInt64()
$peakEngineBusy = $null
if ($engines.Count -gt 0) {
    $peakEngineBusy = [double](($engines | Measure-Object -Property CookedValue -Maximum).Maximum)
}
[ordered]@{
    gpuAdapter = 'AMD Radeon RX 7900 XT'
    gpuLuid = ('0x{0:x8}:0x{1:x8}' -f $high,$adapter.LuidLow)
    gpuDedicatedUsedBytes = [long]$dedicatedBytes
    gpuTotalCommittedBytes = [long]$committedBytes
    gpuCommittedBytes = [long][Math]::Max($dedicatedBytes, $committedBytes)
    gpuTotalBytes = [long]$totalBytes
    gpuFreeBytes = [long][Math]::Max([double]0, $totalBytes - [Math]::Max($dedicatedBytes, $committedBytes))
    gpuPeakEngineBusyPct = $peakEngineBusy
    sampledAt = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json -Compress
