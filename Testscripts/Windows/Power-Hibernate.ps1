# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
<#
.Synopsis
	Perform a simple VM hibernation in Azure
	This feature might be available in kernel 5.7 or later. By the time,
	customized kernel will be built.
	# Hibernation will be supported in the general purpose VM with max 16G vRAM
	# and the GPU VMs with max 112G vRAM.


.Description
	This test can be performed in Azure and Hyper-V both. But this script only covers Azure.
	1. Prepare swap space for hibernation
	2. Compile a new kernel (optional)
	3. Update the grub.cfg with resume=UUID=xxxx where is from blkid swap disk
	4. Hibernate the VM, and verify the VM status
	5. Resume the VM and verify the VM status.
	6. Verify no kernel panic or call trace
	7. [SRIOV]Verify the tx_queue count and interrupts count are not changed
	8. [SRIOV]Verify the TX/RX packets keep increasing after resuming
#>

param([object] $AllVmData, [object]$TestParams)

function Main {
	param($AllVMData, $TestParams)
	$currentTestResult = Create-TestResultObject
	try {
		$maxKernelCompileMin = 90
		$testResult = $resultFail
		Write-LogDbg "Prepare swap space for VM $($AllVMData.RoleName) in RG $($AllVMData.ResourceGroupName)."
		# Prepare the swap space in the target VM
		$rgName = $AllVMData.ResourceGroupName
		$vmName = $AllVMData.RoleName
		$location = $AllVMData.Location
		$storageType = 'StandardSSD_LRS'
		$dataDiskName = $vmName + '_datadisk1'
		$defaultHibernateLoop = 1
		$isStress = $false

		#region Generate constants.sh
		# We need to add extra parameters to constants.sh file apart from parameter properties defined in XML.
		# Hence, we are generating constants.sh file again in test script.

		Write-LogInfo "Generating constants.sh ..."
		$constantsFile = "$LogDir\constants.sh"
		foreach ($TestParam in $CurrentTestData.TestParameters.param) {
			Add-Content -Value "$TestParam" -Path $constantsFile
			Write-LogInfo "$TestParam added to constants.sh"
			if ($TestParam -imatch "hb_loop=") {
				# Overwrite new max Iteration of VM hibernation and online stress test
				$defaultHibernateLoop = [int]($TestParam.Replace("hb_loop=", "").Trim('"'))
				$isStress = $true
			}
		}

		Write-LogInfo "constants.sh created successfully..."
		#endregion

		#region Add a new swap disk to Azure VM
		$diskConfig = New-AzDiskConfig -SkuName $storageType -Location $location -CreateOption Empty -DiskSizeGB 1024
		$dataDisk1 = New-AzDisk -DiskName $dataDiskName -Disk $diskConfig -ResourceGroupName $rgName

		$vm = Get-AzVM -Name $vmName -ResourceGroupName $rgName
		Start-Sleep -s 30
		$vm = Add-AzVMDataDisk -VM $vm -Name $dataDiskName -CreateOption Attach -ManagedDiskId $dataDisk1.Id -Lun 1
		Start-Sleep -s 30

		$ret_val = Update-AzVM -VM $vm -ResourceGroupName $rgName
		Write-LogInfo "Updated the VM with a new data disk"
		Write-LogInfo "Waiting for 30 seconds for configuration sync"
		# Wait for disk sync with Azure host
		Start-Sleep -s 60

		# Verify the new data disk addition
		if ($ret_val.IsSuccessStatusCode) {
			Write-LogInfo "Successfully add a new disk to the Resource Group, $($rgName)"
		} else {
			Write-LogErr "Failed to add a new disk to the Resource Group, $($rgname)"
			throw "Failed to add a new disk"
		}

		$testcommand = @"
echo disk > /sys/power/state
"@
		Set-Content "$LogDir\test.sh" $testcommand

		#region Upload files to VM
		foreach ($VMData in $AllVMData) {
			Copy-RemoteFiles -uploadTo $VMData.PublicIP -port $VMData.SSHPort -files "$constantsFile,$($CurrentTestData.files),$LogDir\*.sh" -username $user -password $password -upload
			Write-LogInfo "Copied the script files to the VM"
		}
		#endregion

		# Configuration for the hibernation
		Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "/home/$user/SetupHbKernel.sh" -RunInBackground -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
		Write-LogInfo "Executed SetupHbKernel script inside VM"

		# Wait for kernel compilation completion. 90 min timeout
		$timeout = New-Timespan -Minutes $maxKernelCompileMin
		$sw = [diagnostics.stopwatch]::StartNew()
		while ($sw.elapsed -lt $timeout) {
			Wait-Time -seconds 30
			$state = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat /home/$user/state.txt" -runAsSudo
			Write-LogDbg "state is $state"
			if ($state -eq "TestCompleted") {
				$kernelCompileCompleted = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "cat /home/$user/constants.sh | grep setup_completed=0" -runAsSudo
				if ($kernelCompileCompleted -ne "setup_completed=0") {
					Write-LogErr "SetupHbKernel.sh run finished on $($VMData.RoleName) but setup was not successful!"
				} else {
					Write-LogInfo "SetupHbKernel.sh finished on $($VMData.RoleName)"
				}
				break
			} elseif ($state -eq "TestSkipped") {
				Write-LogInfo "SetupHbKernel.sh finished with SKIPPED state!"
				$resultArr = $resultSkipped
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} elseif ($state -eq "TestFailed") {
				Write-LogErr "SetupHbKernel.sh didn't finish successfully!"
				$resultArr = $resultFail
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} elseif ($state -eq "TestAborted") {
				Write-LogInfo "SetupHbKernel.sh finished with Aborted state!"
				$resultArr = $resultAborted
				$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
				return $currentTestResult.TestResult
			} else {
				Write-LogInfo "SetupHbKernel.sh is still running in the VM!"
			}
		}

		# Reboot VM to apply swap setup changes
		Write-LogInfo "Rebooting All VMs!"
		$TestProvider.RestartAllDeployments($AllVMData)

		for ($iteration=1; $iteration -le $defaultHibernateLoop; $iteration++) {
			if ($isStress) {
				Write-LogInfo "Running Hibernation stress test in the iteration - $iteration"
				# Clear dmesg log before running test
				Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "dmesg -c" -runAsSudo -ignoreLinuxExitCode:$true | Out-Null
			}
			# Check the VM status before hibernation
			$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
			if ($vmStatus.Statuses[1].DisplayStatus -eq "VM running") {
				Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is running before hibernation"
			} else {
				Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Did not verify the VM status running before hibernation"
				Write-LogDbg $vmStatus
				throw "Did not verify VM status running before hibernate"
			}

			$getvf = @"
cat /proc/net/dev | grep -v Inter | grep -v face > netdev.log
while IFS= read -r line
do
	case "`$line" in
		*lo* );;
		*eth0* );;
		* ) echo `$line | cut -d ':' -f 1;;
	esac
done < netdev.log
"@
			Set-Content "$LogDir\getvf.sh" $getvf

			$setupcommand = @"
source utils.sh
update_repos
install_package "ethtool"
"@
			Set-Content "$LogDir\setup.sh" $setupcommand

			#region Upload files to VM
			foreach ($VMData in $AllVMData) {
				Copy-RemoteFiles -uploadTo $VMData.PublicIP -port $VMData.SSHPort -files "$constantsFile,$($CurrentTestData.files),$LogDir\*.sh" -username $user -password $password -upload
				Write-LogInfo "Copied the script files to the VM"
				Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "bash /home/$user/setup.sh" -runAsSudo
			}
			#endregion

			# Install GPU driver (for POWER-HIBERNATE-GPU case)
			if ($TestParams.CUDADriverVersion) {
				$currentTestResult = Create-TestResultObject
				$resultArr = @()
				$testScript = "gpu-driver-install.sh"
				$driverLoaded = $nul

				# This covers NV and NVv3 series
				if ($allVMData.InstanceSize -imatch "Standard_NV") {
					$driver = "GRID"
					Write-LogDbg "Verfied this instance is with GRID device driver"
				# NC and ND series use CUDA
				} elseif ($allVMData.InstanceSize -imatch "Standard_NC" -or $allVMData.InstanceSize -imatch "Standard_ND") {
					$driver = "CUDA"
					Write-LogDbg "Verified this instance is with CUDA device driver"
				} else {
					Write-LogErr "Azure VM size $($allVMData.InstanceSize) not supported in automation!"
					$currentTestResult.TestResult = Get-FinalResultHeader -resultarr "ABORTED"
					return $currentTestResult
				}
				$currentTestResult.TestSummary += New-ResultSummary -metaData "Using nVidia driver" -testName $CurrentTestData.testName -testResult $driver
				$cmdAddConstants = "echo -e `"driver=$($driver)`" >> constants.sh"
				Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP -port $allVMData.SSHPort `
					-command $cmdAddConstants | Out-Null
				Write-LogDbg "Added GPU driver name to constants.sh file"

				# Start the test script
				Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $user `
					-password $password -command "bash /home/$user/${testscript}" -runMaxAllowedTime 1800 -ignoreLinuxExitCode -runAsSudo | Out-Null
				Write-LogDbg "Ran test script $testscript in the Guest OS"

				$installState = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort -username $user `
					-password $password -command "cat /home/$user/state.txt"
				Write-LogDbg "Found installState: $installState"

				if ($installState -eq "TestSkipped") {
					$currentTestResult.TestResult = Get-FinalResultHeader -resultarr "SKIPPED"
					return $currentTestResult
				}

				if ($installState -imatch "TestAborted") {
					Write-LogErr "GPU drivers installation aborted"
					$currentTestResult.TestResult = Get-FinalResultHeader -resultarr "ABORTED"
					Collect-Logs
					return $currentTestResult
				}

				if ($installState -ne "TestCompleted") {
					Write-LogErr "Unable to install the GPU drivers!"
					$currentTestResult.TestResult = Get-FinalResultHeader -resultarr "FAIL"
					Collect-Logs
					return $currentTestResult
				}

				# If CUDA, enable persistent mode, or cannot get GPU interrupts
				if ($driver -eq "CUDA") {
					Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "systemctl enable nvidia-persistenced" -runAsSudo
				}
				# Restart VM to load the driver and run validation
				if (-not $TestProvider.RestartAllDeployments($allVMData)) {
					Write-LogErr "Unable to connect to VM after restart!"
					$currentTestResult.TestResult = Get-FinalResultHeader -resultarr "ABORTED"
					return $currentTestResult
				}
				# Mandatory to have the nvidia driver loaded after restart
				$driverLoaded = Run-LinuxCmd -username $user -password $password -ip $allVMData.PublicIP `
					-port $allVMData.SSHPort -command "lsmod | grep nvidia" -ignoreLinuxExitCode
				if ($null -eq $driverLoaded) {
					Write-LogErr "GPU driver is not loaded after VM restart!"
					$currentTestResult.TestResult = Get-FinalResultHeader -resultarr "FAIL"
					Collect-Logs
					return $currentTestResult
				}
				# Verify nvidia-smi validation
				$nvidiasmi = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort `
					-username $user -password $password "nvidia-smi" -ignoreLinuxExitCode -runAsSudo
				Write-LogInfo "nvidiasmi output:"
				Write-LogInfo "$nvidiasmi"
				if ( $nvidiasmi ) {
					Write-LogInfo "Successfully fetched the nvidia-smi command result"
				} else {
					Write-LogErr "Failed to fetch the nvidia-smi command result"
					throw "Fail to execute nvidia-smi before hibernation"
				}
			}

			# Getting queue counts and interrupt counts before hibernation
			$vfname = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "bash /home/$user/getvf.sh" -runAsSudo
			if ( $vfname -ne '' ) {
				$tx_queue_count1 = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "ethtool -l $vfname | grep -i tx | tail -n 1 | cut -d ':' -f 2 | tr -d '[:space:]'" -runAsSudo
				$interrupt_count1 = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "cat /proc/interrupts | grep -i mlx | grep -i msi | wc -l" -runAsSudo
			}
			# Hibernate the VM
			Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "/home/$user/test.sh" -runAsSudo -RunInBackground -ignoreLinuxExitCode:$true | Out-Null
			Write-LogInfo "Sent hibernate command to the VM and continue checking its status in every 15 seconds until 20 minutes timeout"

			# Verify the VM status
			# Can not find if VM hibernation completion or not as soon as it disconnects the network. Assume it is in timeout.
			$timeout = New-Timespan -Minutes 20
			$sw = [diagnostics.stopwatch]::StartNew()
			while ($sw.elapsed -lt $timeout) {
				Wait-Time -seconds 15
				$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
				if ($vmStatus.Statuses[1].DisplayStatus -eq "VM stopped") {
					break
				} else {
					Write-LogInfo "VM status is not stopped. Waiting for 15 seconds..."
				}
			}
			if ($vmStatus.Statuses[1].DisplayStatus -eq "VM stopped") {
				Write-LogInfo "$($vmStatus.Statuses[1].DisplayStatus): Verified successfully VM status is stopped after hibernation command sent"
			} else {
				Write-LogErr "$($vmStatus.Statuses[1].DisplayStatus): Did not verify the VM status stopped after hibernation command sent"
				throw "Did not verify the VM status stopped after hibernation starts"
			}

			# For POWER-HIBERNATE-SRIOV-DEALLOCATE case
			if ($TestParams.deallocate_vm) {
				Stop-AzVM -Name $vmName -ResourceGroupName $rgName -Force | Out-Null
				Write-LogInfo "VM is deallocated."
			}

			# Resume the VM
			Start-AzVM -Name $vmName -ResourceGroupName $rgName -NoWait | Out-Null
			Write-LogInfo "Waked up the VM $vmName in Resource Group $rgName and continue checking its status in every 15 seconds until 57 minutes timeout"

			# Get PublicIP if the VM has been deallocated
			if ($TestParams.deallocate_vm) {
				$timeout = New-Timespan -Minutes 20
				$sw = [diagnostics.stopwatch]::StartNew()
				$publicIpName = (Get-AzResource -ResourceGroupName $rgName -ResourceType "Microsoft.Network/publicIPAddresses").Name | select -Last 1
				while ($sw.elapsed -lt $timeout) {
					Wait-Time -seconds 15
					$AllVmData.PublicIp = (Get-AzPublicIpAddress -ResourceGroupName $rgName -Name $publicIpName).IpAddress
					if ($AllVmData.PublicIp -ne "Not Assigned") {
						break
					} else {
						Write-LogInfo "VM Public IP is not assigned. Waiting for 15 seconds..."
					}
				}
				if ($AllVmData.PublicIp -eq "Not Assigned") {
					Write-LogErr "Cannot get new Public IP address. Abort the test."
					$testResult = $resultAborted
					throw "Cannot get new Public IP address"
				}
			}

			# Wait for VM resume for 57 min-timeout
			$timeout = New-Timespan -Minutes 57
			$sw = [diagnostics.stopwatch]::StartNew()
			$vmCount = $AllVMData.Count
			while ($sw.elapsed -lt $timeout) {
				Wait-Time -seconds 15
				$state = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "date > /dev/null; echo $?"
				Write-LogDbg "state is $state"
				if ($state) {
					# Wait for 10 seconds for syslog sync after resume.
					Start-Sleep -s 10
					Write-LogInfo "VM $($AllVMData.RoleName) resumed successfully"
					$vmCount--
					break
				} else {
					Write-LogInfo "VM is still resuming!"
				}
			}

			if ($vmCount -le 0) {
				Write-LogInfo "VM resume completed"
			} else {
				# Either VM hang or VM resume needs longer time.
				throw "VM resume did not finish or did not have the expected log message"
			}

			# Verify the VM status after VM is accessible.
			# Read VM status from the host during 10 min-timeout
			$timeout = New-Timespan -Minutes 10
			$sw = [diagnostics.stopwatch]::StartNew()
			$_verified = 0
			while ($sw.elapsed -lt $timeout) {
				Wait-Time -seconds 15
				$vmStatus = Get-AzVM -Name $vmName -ResourceGroupName $rgName -Status
				if ($vmStatus.Statuses[1].DisplayStatus -eq "VM running") {
					$_verified = 1
					break
				} else {
					Write-LogDbg "$($vmStatus.Statuses[1].DisplayStatus): VM status is not 'VM running' yet. Check the next status in 15 seconds."
				}
			}

			if ($_verified -eq 1) {
				Write-LogInfo "Successfully verified VM status - $vmStatus.Statuses[1].DisplayStatus"
			} else {
				throw "Did not verify the VM status running in the last 10-min checking, but found $vmStatus.Statuses[1].DisplayStatus"
			}

			# Verify the kernel panic, call trace or fatal error
			$calltrace_filter = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "dmesg | grep -iE '(call trace|fatal error)'" -runAsSudo -ignoreLinuxExitCode:$true

			if ($calltrace_filter -ne "") {
				Write-LogErr "Found Call Trace or Fatal error in dmesg"
				# The throw statement is commented out because this is linux-next, so there is high chance to get call trace from other issue. For now, only print the error.
				# throw "Call trace in dmesg"
			} else {
				Write-LogInfo "Not found Call Trace and Fatal error in dmesg"
			}

			# Check the system log if it shows Power Management log
			"hibernation entry", "hibernation exit" | ForEach-Object {
				$pm_log_filter = Run-LinuxCmd -ip $AllVMData[0].PublicIP -port $AllVMData[0].SSHPort -username $user -password $password -command "source utils.sh; found_sys_log '$_';echo $?" -ignoreLinuxExitCode:$true
				Write-LogInfo "Searching the keyword: $_"
				if ($pm_log_filter -eq "0") {
					Write-LogErr "Could not find Power Management log in dmesg"
					throw "Missing PM logging in dmesg"
				} else {
					Write-LogInfo "Successfully found Power Management log in dmesg"
				}
			}

			# Verify GPU driver status and MSI interrupts (for POWER-HIBERNATE-GPU case)
			if ($TestParams.CUDADriverVersion) {
				$nvidiasmi = Run-LinuxCmd -ip $allVMData.PublicIP -port $allVMData.SSHPort `
					-username $user -password $password "nvidia-smi" -ignoreLinuxExitCode -runAsSudo
				Write-LogInfo "nvidia-smi output:"
				Write-LogInfo "$nvidiasmi"
				if ( $nvidiasmi ) {
					Write-LogInfo "Successfully fetched the nvidia-smi command result"
				} else {
					Write-LogErr "Failed to fetch the nvidia-smi command result"
					throw "Fail to execute nvidia-smi after waking up"
				}
			}
			# Verify MSI interrupts keep increasing after waking up
			$msi_interrupt_value1 = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password `
				-command "cat /proc/interrupts | grep msi -i | awk '{c=0;for(i=2;i<2+`"'`$(nproc)'`";++i){c+=`$i};print c}' | awk '{SUM+=`$1}END{print SUM}'" -runAsSudo
			Start-Sleep -s 10
			$msi_interrupt_value2 = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password `
				-command "cat /proc/interrupts | grep msi -i | awk '{c=0;for(i=2;i<2+`"'`$(nproc)'`";++i){c+=`$i};print c}' | awk '{SUM+=`$1}END{print SUM}'" -runAsSudo
			if ($msi_interrupt_value1 -le $msi_interrupt_value2) {
				Write-LogErr "First check, MSI interrupts - $msi_interrupt_value1. Second check, MSI interrupts of nvidia driver - $msi_interrupt_value2"
				throw "GPU MSI interrupt stop increasing after waking up."
			} else {
				Write-LogInfo "First check, MSI interrupts of nvidia driver - $msi_interrupt_value1. Second check, MSI interrupts of nvidia driver - $msi_interrupt_value2"
				Write-LogInfo "Successfully verified GPU MSI interrupt keep increasing after waking up"
			}
		}

		# Getting queue counts and interrupt counts after resuming.
		$vfname = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "bash /home/$user/getvf.sh" -runAsSudo
		if ($vfname -ne '') {
			$tx_queue_count2 = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "ethtool -l ${vfname} | grep -i tx | tail -n 1 | cut -d ':' -f 2 | tr -d '[:space:]'" -runAsSudo
			$interrupt_count2 = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "cat /proc/interrupts | grep -i mlx | grep -i msi | wc -l" -runAsSudo

			if ($tx_queue_count1 -ne $tx_queue_count2) {
				Write-LogErr "Before hibernation, Tx queue count - $tx_queue_count1. After waking up, Tx queue count - $tx_queue_count2"
				throw "Tx queue counts changed after waking up."
			} else {
				Write-LogInfo "Successfully verified Tx queue count matching in Current hardware settings."
			}

			if ($interrupt_count1 -ne $interrupt_count2) {
				Write-LogErr "Before hibernation, MSI interrupts of mlx driver - $interrupt_count1. After waking up, MSI interrupts of mlx driver - $interrupt_count2"
				throw "MSI interrupt counts changed after waking up."
			} else {
				Write-LogInfo "Successfully verified MSI interrupt counts matching"
			}

			# Verify the TX/RX packets keep increasing after waking up
			$tx_packets_first = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "ethtool -S ${vfname} | grep tx_packets: | awk '{print `$2}'" -runAsSudo
			$rx_packets_first = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "ethtool -S ${vfname} | grep rx_packets: | awk '{print `$2}'" -runAsSudo
			Start-Sleep -s 10
			$tx_packets_second = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "ethtool -S ${vfname} | grep tx_packets: | awk '{print `$2}'" -runAsSudo
			$rx_packets_second = Run-LinuxCmd -ip $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -command "ethtool -S ${vfname} | grep rx_packets: | awk '{print `$2}'" -runAsSudo
			if ($tx_packets_first -ge $tx_packets_second) {
				Write-LogErr "First collected TX packets: $tx_packets_first. Second collected TX packets: $tx_packets_second"
				throw "TX packets stopped increasing after waking up."
			} else {
				Write-LogInfo "Successfully verified TX packets increasing"
			}
			if ($rx_packets_first -ge $rx_packets_second) {
				Write-LogErr "First collected RX packets: $rx_packets_first. Second collected RX packets: $rx_packets_second"
				throw "RX packets stopped increasing after waking up."
			} else {
				Write-LogInfo "Successfully verified RX packets increasing"
			}
		} else {
			Write-LogInfo "No VF NIC found. Skip VF verification."
		}

		$testResult = $resultPass
		Copy-RemoteFiles -downloadFrom $AllVMData.PublicIP -port $AllVMData.SSHPort -username $user -password $password -download -downloadTo $LogDir -files "*.log" -runAsSudo
	} catch {
		$ErrorMessage =  $_.Exception.Message
		$ErrorLine = $_.InvocationInfo.ScriptLineNumber
		Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
	} finally {
		if (!$testResult) {
			$testResult = $resultAborted
		}
		$resultArr = $testResult
	}

	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult
}

Main -AllVmData $AllVmData -CurrentTestData $CurrentTestData -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))
