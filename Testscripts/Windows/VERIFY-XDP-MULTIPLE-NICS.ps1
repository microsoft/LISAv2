# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Description
    This script deploys the VMs, verifies xdp working
    with 2 SRIOV-enabled nics i.e. eth1 and eth2
#>

param([object] $AllVmData,
    [object] $CurrentTestData)

$MIN_KERNEL_VERSION = "5.6"
$iface1 = "eth1"
$iface2 = "eth2"

# This function will start ping and xdpdump on given VM
# returns XDPDump process id.
function XDPPing {
    $clientVMData = $args[0]
    $IP = $args[1]
    $NIC = $args[2]

    # Start Ping test
    $pingCommand = "ping -I $NIC -c 30 $IP > ~/pingOut_$NIC.txt"
    Write-LogInfo "Starting command $pingCommand on $($clientVMData.RoleName)"
    Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $user -password $password `
        -command $pingCommand -RunInBackground -runAsSudo
    # Start XDPDump
    $xdpCommand = "cd /root/bpf-samples/xdpdump && timeout 10 ./xdpdump -i $NIC > ~/xdpdumpout_$NIC.txt"
    Write-LogInfo "Starting command $xdpCommand on $($clientVMData.RoleName)"
    $testJob = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $user -password $password `
        -command $xdpCommand -RunInBackground -runAsSudo
    return $testJob
}

function Main {
    try {
        $noClient = $true
        $noServer = $true
        foreach ($vmData in $allVMData) {
            if ($vmData.RoleName -imatch "client") {
                $clientVMData = $vmData
                $noClient = $false
            }
            elseif ($vmData.RoleName -imatch "server") {
                $noServer = $false
                $serverVMData = $vmData
            }
        }
        if ($noClient) {
            Throw "No client VM defined. Aborting Test."
        }
        if ($noServer) {
            Throw "No server VM defined. Aborting Test."
        }

        # CONFIGURE VM Details
        Write-LogInfo "CLIENT VM details :"
        Write-LogInfo "  RoleName : $($clientVMData.RoleName)"
        Write-LogInfo "  Public IP : $($clientVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($clientVMData.SSHPort)"
        Write-LogInfo "  Internal IP : $($clientVMData.InternalIP)"
        Write-LogInfo "SERVER VM details :"
        Write-LogInfo "  RoleName : $($serverVMData.RoleName)"
        Write-LogInfo "  Public IP : $($serverVMData.PublicIP)"
        Write-LogInfo "  SSH Port : $($serverVMData.SSHPort)"
        Write-LogInfo "  Internal IP : $($serverVMData.InternalIP)"

        # Check for compatible kernel
        $currentKernelVersion = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort `
                -username $user -password $password -command "uname -r"
        # ToDo: Update Minimum kernel version check once patches are in downstream distro.
        if ((Compare-KernelVersion $currentKernelVersion $MIN_KERNEL_VERSION) -lt 0 -or $global:DetectedDistro -ne "UBUNTU"){
            Write-LogInfo "Minimum kernel version required for XDP: $MIN_KERNEL_VERSION."`
                "Unsupported kernel version: $currentKernelVersion or Unsupported distro: $($global:DetectedDistro)."
            return $global:ResultSkipped
        }

        # PROVISION VMS
        Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"

        # Generate constants.sh and write all VM info into it
        Write-LogInfo "Generating constants.sh ..."
        $constantsFile = "$LogDir\constants.sh"
        Set-Content -Value "# Generated by Azure Automation." -Path $constantsFile
        Add-Content -Value "ip=$($clientVMData.InternalIP)" -Path $constantsFile
        Add-Content -Value "nicName=$iface1" -Path $constantsFile
        foreach ($param in $currentTestData.TestParameters.param) {
            Add-Content -Value "$param" -Path $constantsFile
        }
        Write-LogInfo "constants.sh created successfully..."
        Write-LogInfo (Get-Content -Path $constantsFile)

        # Build and Install XDP Dump application
        $installXDPCommand = @"
bash XDPDumpSetup.sh 2>&1 > ~/xdpConsoleLogs.txt
. utils.sh
collect_VM_properties
"@
        Set-Content "$LogDir\StartXDPSetup.sh" $installXDPCommand
        Copy-RemoteFiles -uploadTo $clientVMData.PublicIP -port $clientVMData.SSHPort `
            -files "$constantsFile,$LogDir\StartXDPSetup.sh" `
            -username $user -password $password -upload -runAsSudo
        $testJob = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort `
            -username $user -password $password -command "bash StartXDPSetup.sh" `
            -RunInBackground -runAsSudo
        # Terminate process if ran more than 5 mins
        # TODO: Check max installation time for other distros when added
        $timer = 0
        while ((Get-Job -Id $testJob).State -eq "Running") {
            $currentStatus = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort `
                -username $user -password $password -command "tail -2 ~/xdpConsoleLogs.txt | head -1" -runAsSudo
            Write-LogInfo "Current Test Status: $currentStatus"
            Wait-Time -seconds 20
            $timer += 1
            if ($timer -gt 15) {
                Throw "XDPSetup did not stop after 5 mins. Please check logs"
            }
        }

        $currentState = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort `
            -username $user -password $password -command "cat state.txt" -runAsSudo
        if ($currentState -imatch "TestCompleted") {
            Write-LogInfo "XDPSetup successfully ran on $($clientVMDAta.RoleName)"

            # check interfaces are present in the VM
            $ethString = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $user -password $password `
                    -command "ls /sys/class/net/ | grep -w '$iface1\|$iface2'"
            if ($ethString -notmatch $iface1 -or $ethString -notmatch $iface2){
                Throw "Testcase aborted as either $iface1 or $iface2 interface not present"
            }

            # start XDPDUMP on interfaces
            $testJob_1 = XDPPing $clientVMData $serverVMData.SecondInternalIP $iface1
            $testJob_2 = XDPPing $clientVMData "10.0.2.5" $iface2

            # Terminate process if ran more than 5 mins
            # TODO: Check max installation time for other distros when added
            $timer = 0
            while ((Get-Job -Id $testJob_1).State -eq "Running" -or (Get-Job -Id $testJob_2).State -eq "Running") {
                $currentStatus = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $user -password $password `
                    -command "tail -2 ~/xdpdumpout_$iface1.txt | head -1" -runAsSudo
                Write-LogInfo "Current Test Status: $iface1 : $currentStatus"
                $currentStatus = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $user -password $password `
                    -command "tail -2 ~/xdpdumpout_$iface2.txt | head -1" -runAsSudo
                Write-LogInfo "Current Test Status: $iface2 : $currentStatus"
                Wait-Time -seconds 20
                $timer += 1
                if ($timer -gt 15) {
                    Throw "XDPDump did not stop after 5 mins. Please check logs"
                }
            }

            $currentStatus_1 = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $user -password $password `
                -command "tail -1 ~/xdpdumpout_$iface1.txt" -runAsSudo
            $currentStatus_2 = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $user -password $password `
                -command "tail -1 ~/xdpdumpout_$iface2.txt" -runAsSudo
            if ( ($currentStatus_1 -match "unloading xdp") -and ($currentStatus_2 -match "unloading xdp") ) {
                $testResult = "PASS"
            } else {
                Throw "XDPDump aborted. Last known status : $currentStatus_1 & $currentStatus_2."
            }
            Write-LogInfo "Successfully ran xdpdump on both the network interfaces"

        }   elseif ($currentState -imatch "TestAborted") {
            Write-LogErr "Test Aborted. Last known status: $currentStatus."
            $testResult = "ABORTED"
        }   elseif ($currentState -imatch "TestSkipped") {
            Write-LogErr "Test Skipped. Last known status: $currentStatus"
            $testResult = "SKIPPED"
        }   elseif ($currentState -imatch "TestFailed") {
            Write-LogErr "Test failed. Last known status: $currentStatus."
            $testResult = "FAIL"
        }   else {
            Write-LogErr "Test execution is not successful, check test logs in VM."
            $testResult = "ABORTED"
        }

        Copy-RemoteFiles -downloadFrom $clientVMData.PublicIP -port $clientVMData.SSHPort `
            -username $user -password $password -download `
            -downloadTo $LogDir -files "*.txt, *.log"
    } catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    } finally {
        if (!$testResult) {
            $testResult = "ABORTED"
        }
        $resultArr += $testResult
    }
    Write-LogInfo "Test result: $testResult"
    return $testResult
}

Main
