# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData,
      [object] $CurrentTestData)

function Main {
    $currentTestResult = Create-TestResultObject
    try {
        $count = 0
        $VM = $allVMData
        $ResourceGroupUnderTest = $VM.ResourceGroupName
        $VirtualMachine = Get-AzVM -ResourceGroupName $VM.ResourceGroupName -Name $VM.RoleName
        $diskCount = (Get-AzVMSize -Location $allVMData.Location | Where-Object {$_.Name -eq $allVMData.InstanceSize}).MaxDataDiskCount
        $storageProfile = (Get-AzVM -ResourceGroupName $AllVMData.ResourceGroupName -Name $AllVMData.RoleName).StorageProfile
        $allDiskNames = @()
        $allUnmanagedDataDisks = @()
        Write-LogInfo "Max $diskCount Disks will be attached to VM"
        Write-LogInfo "--------------------------------------------------------"
        Write-LogInfo "Serial Addition of Data Disks"
        Write-LogInfo "--------------------------------------------------------"
        if ($allVMData.InstanceSize -imatch "Standard_[DE]\d+pl?s_.") {
            # These VM sizes don't have local disk. So the attached disk starts from dev/sdb
            $diskPattern = "Disk /dev/sd[a-z][a-z]|sd[b-z]:"
        } else {
            $diskPattern = "Disk /dev/sd[a-z][a-z]|sd[c-z]:"
        }
        While ($count -lt $diskCount) {
            $count += 1
            $verifiedDiskCount = 0
            $diskName = "disk" + $count.ToString()
            $diskSizeinGB = "10"
            $allDiskNames += $diskName
            if ($storageProfile.OsDisk.ManagedDisk) {
                # Add managed data disks
                $storageType = 'Standard_LRS'
                $diskConfig = New-AzDiskConfig -SkuName $storageType -Location $AllVMData.Location -CreateOption Empty -DiskSizeGB $diskSizeinGB
                Write-LogInfo "#$count - Adding a managed empty data disk of size $diskSizeinGB GB"
                $dataDisk = New-AzDisk -DiskName $diskName -Disk $diskConfig -ResourceGroupName $AllVMData.ResourceGroupName
                Add-AzVMDataDisk -VM $virtualMachine -Name $diskName -CreateOption Attach -ManagedDiskId $dataDisk.Id -Lun $count | Out-Null
                Write-LogInfo "#$count - Successfully created a managed empty data disk of size $diskSizeinGB GB"
            } else {
                # Add unmanaged data disks
                $VHDuri = $VirtualMachine.StorageProfile.OsDisk.Vhd.Uri
                $VHDUri = $VHDUri.Replace("osdisk", $diskName)
                Write-LogInfo "#$count - Adding an unmanaged empty data disk of size $diskSizeinGB GB"
                $Null = Add-AzVMDataDisk -VM $VirtualMachine -Name $diskName -DiskSizeInGB $diskSizeinGB -LUN $count -VhdUri $VHDuri.ToString() -CreateOption Empty
                Write-LogInfo "#$count - Successfully created an unmanaged empty data disk of size $diskSizeinGB GB"
                $allUnmanagedDataDisks += $VHDUri.ToString().Split('/')[-1]
            }
            $Null = Update-AzVM -VM $VirtualMachine -ResourceGroupName $ResourceGroupUnderTest
            Write-LogInfo "#$count - Successfully added an empty data disk to the VM of size $diskSizeinGB"
            Write-LogInfo "Verifying if data disk is added to the VM: Running fdisk on remote VM"
            $fdiskOutput = Run-LinuxCmd -username $user -password $password -ip $VM.PublicIP -port $VM.SSHPort -command "/sbin/fdisk -l | grep /dev/sd" -runAsSudo
            foreach ($line in ($fdiskOutput.Split([Environment]::NewLine))) {
                if ($line -imatch $diskPattern -and ([int]($line.Split()[2]) -ge [int]$diskSizeinGB)) {
                    Write-LogInfo "Data disk is successfully attached to the VM: $line"
                    $verifiedDiskCount += 1
                }
            }
        }
        Copy-RemoteFiles -uploadTo $allVMData.PublicIP -port $allVMData.SSHPort -files $currentTestData.files -username $user -password $password -upload
        $null = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "chmod +x *" -runAsSudo
        $testJob = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $user -password $password -command "bash ./nobarrier.sh > nobarrierConsole.txt" -RunInBackground -runAsSudo
        while ( (Get-Job -Id $testJob).State -eq "Running" ) {
            $currentStatus = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "tail -1 ./nobarrierConsole.txt" -runAsSudo
            Write-LogInfo "Current Test Status : $currentStatus"
            Wait-Time -seconds 20
        }
        $finalStatus = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort -command "cat ./state.txt" -runAsSudo
        if ( $finalStatus -imatch "TestFailed") {
            Write-LogErr "Test failed. Last known status : $currentStatus."
            $testResult = "FAIL"
        }
        elseif ( $finalStatus -imatch "TestAborted") {
            Write-LogErr "Test Aborted. Last known status : $currentStatus."
            $testResult = "ABORTED"
        }
        elseif ( $finalStatus -imatch "TestCompleted") {
            Write-LogInfo "Test Completed."
            $testResult = "PASS"
            Write-LogInfo "Parallel Removal of Data Disks from the VM"
            Remove-AzVMDataDisk -VM $virtualMachine -DataDiskNames $allDiskNames | Out-Null
            $updateVM2 = Update-AzVM -VM $virtualMachine -ResourceGroupName $AllVMData.ResourceGroupName
            if ($updateVM2.IsSuccessStatusCode) {
                Write-LogInfo "Successfully removed the data disk from the VM"
                # Delete unmanaged data disks
                if (!$storageProfile.OsDisk.ManagedDisk) {
                    $osVhdStorageAccountName = $storageProfile.OsDisk.Vhd.Uri.Split(".").split("/")[2]
                    $osVhdStorageAccount = Get-AzStorageAccount | where { $_.StorageAccountName -eq $osVhdStorageAccountName }
                    foreach ($unmanagedDataDisk in $allUnmanagedDataDisks) {
                        Write-LogInfo "Delete unmanaged data disks $unmanagedDataDisk"
                        $osVhdStorageAccount | Remove-AzStorageBlob -Container $VHDUri.ToString().Split('/')[-2] -Blob $unmanagedDataDisk -Verbose -Force
                    }
                }
            } else {
                throw "Failed to remove the data disk from the VM"
            }
        }
        $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$($allVMData.InstanceSize) : Number of Disk Attached - $diskCount" `
            -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogInfo "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    finally {
        if (!$testResult) {
            $testResult = "Aborted"
            $CurrentTestResult.TestSummary += New-ResultSummary -testResult $testResult -metaData "$($allVMData.InstanceSize) : Number of Disk Attached - $diskCount" `
                -checkValues "PASS,FAIL,ABORTED" -testName $currentTestData.testName
        }
        $resultArr += $testResult
    }
    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    return $currentTestResult
}

Main
