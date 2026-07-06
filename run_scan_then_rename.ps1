param(
  [int]$Count = 5,
  [string]$AdbSerial = ""
)

if ($AdbSerial -ne "") {
  pogo workflow --count $Count --adb-serial $AdbSerial
} else {
  pogo workflow --count $Count
}
