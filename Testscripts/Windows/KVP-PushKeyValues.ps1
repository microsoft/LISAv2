# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

<#
.Synopsis
    Linux VM creates a KVP item, then verify from the host.

.Description
    A Linux VM will create a non-intrinsic KVP item.  Then
    verify the host can see the KVP item.
#>

param([String] $TestParams,
      [object] $AllVmData)

function Main {
    param (
        $VMName,
        $HvServer,
        $Ipv4,
        $VMPort,
        $VMUserName,
        $VMPassword,
        $RootDir,
        $TestParams
    )

    $key = $null
    $value = $null

    if (-not $RootDir) {
        Write-LogWarn "No RootDir was specified"
    } else {
        Set-Location $RootDir
    }
    if (-not $TestParams) {
        Write-LogErr "No test parameters specified"
        return "Aborted"
    }

    # For loggine purposes, display the TestParams
    Write-LogDbg "TestParams : '${TestParams}'"

    # Parse the test parameters
    $params = $TestParams.Split(";")
    foreach ($p in $params) {
        $fields = $p.Split("=")
        if ($fields.count -ne 2) {
            continue
        }
        $rValue = $fields[1].Trim()
        switch ($fields[0].Trim()) {
            "key"        { $key       = $rValue }
            "value"      { $value     = $rValue }
            default      {}
        }
    }

    # Ensure all required test parameters were provided
    if (-not $key) {
        Write-LogErr "The 'key' test parameter was not provided"
        return "FAIL"
    }
    if (-not $value) {
        Write-LogErr "The 'value' test parameter was not provided"
        return "FAIL"
    }

    # Verify the Data Exchange Service is enabled for the test VM
    Write-LogInfo "Creating Integrated Service object"
    $des = Get-VMIntegrationService -VMName $VMName -ComputerName $HvServer
    if (-not $des) {
        Write-LogErr "Unable to retrieve Integration Service status from VM '${VMName}'"
        return "FAIL"
    }
    foreach ($svc in $des) {
        if ($svc.Name -eq "Key-Value Pair Exchange") {
            if (-not $svc.Enabled) {
                Write-LogErr "The Data Exchange Service is not enabled for VM '${VMName}'"
                return "FAIL"
            }
            break
        }
    }

    # The kvp_client file should be listed in the <files> tab of
    # the test case definition, which tells the stateEngine to
    # copy the file to the test VM.  Set the x bit on the kvp_client
    # image, then run kvp_client to add a non-intrinsic kvp item
    Write-LogInfo "Trying to detect OS architecture"
    $kvpClient = $null
    $retVal = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "uname -a | grep x86_64" -runAsSudo
    if (-not $retVal) {
        $retVal = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                    -command "uname -a | grep i686" -runAsSudo
        if (-not ($retVal)) {
            $retVal = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                        -command "uname -a | grep aarch64" -runAsSudo
            if (-not ($retVal)) {
                Write-LogErr "Could not determine OS architecture"
                return "FAIL"
            } else {
                Write-LogInfo "arm 64 bit architecture detected"
                $kvpClient = "kvp_client_arm64"
            }
        } else {
            Write-LogInfo "32 bit architecture detected"
            $kvpClient = "kvp_client32"
        }
    } else {
        Write-LogInfo "64 bit architecture detected"
        $kvpClient = "kvp_client64"
    }

    Write-LogInfo "chmod 755 $kvpClient"
    $retVal = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "chmod 755 ./${kvpClient}" -runAsSudo

    Write-LogInfo "$kvp_client append 1 ${key} ${value}"
    $retVal = Run-LinuxCmd -username $VMUserName -password $VMPassword -ip $Ipv4 -port $VMPort `
                -command "./${kvpClient} append 1 ${key} ${value}" -runAsSudo

    # Create a data exchange object and collect non-intrinsic KVP data from the VM
    Write-LogInfo "Collecting nonintrinsic KVP data from guest"
    $vm = Get-WmiObject -ComputerName $HvServer -Namespace root\virtualization\v2 `
            -Query "Select * From Msvm_ComputerSystem Where ElementName=`'$VMName`'"
    if (-not $vm) {
        Write-LogErr "Unable to the VM '${VMName}' on the local host"
        return "FAIL"
    }

    $kvp = Get-WmiObject -ComputerName $HvServer -Namespace root\virtualization\v2 `
            -Query "Associators of {$vm} Where AssocClass=Msvm_SystemDevice ResultClass=Msvm_KvpExchangeComponent"
    if (-not $kvp) {
        Write-LogErr "Unable to retrieve KVP Exchange object for VM '${VMName}'"
        return "FAIL"
    }
    $kvpData = $kvp.GuestExchangeItems
    if (-not $kvpData) {
        Write-LogErr "KVP NonIntrinsic data is null"
        return "FAIL"
    }
    $dict = Convert-KvpToDict $kvpData

    # For logging purposed, display all kvp data
    Write-LogInfo "Non-Intrinsic data"
    foreach ($key in $dict.Keys) {
        $value = $dict[$key]
        Write-LogInfo ("       {0,-27} : {1}" -f $key, $value)
    }

    # Check to make sure the guest created KVP item is returned
    if (-not $dict.ContainsKey($key)) {
        Write-LogErr "The key '${key}' does not exist in the non-intrinsic data"
        return "FAIL"
    }
    $data = $dict[$key]
    if ( $data -ne $value) {
        Write-LogErr "The KVP item has an incorrect value:  ${key} = ${value}"
        return "FAIL"
    }

    # If we made it here, everything worked
    return "PASS"
}

Main -VMName $AllVMData.RoleName -HvServer $GlobalConfig.Global.Hyperv.Hosts.ChildNodes[0].ServerName `
         -Ipv4 $AllVMData.PublicIP -VMPort $AllVMData.SSHPort `
         -VMUserName $user -VMPassword $password -RootDir $WorkingDirectory `
         -TestParams $TestParams
