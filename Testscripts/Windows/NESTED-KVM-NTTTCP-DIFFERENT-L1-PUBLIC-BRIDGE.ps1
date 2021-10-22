# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param([object] $AllVmData, [object] $CurrentTestData)

$testScript = "nested_kvm_ntttcp_different_l1_public_bridge.sh"
if(($($currentTestData.TestName)).Contains("NESTED-KVM-NTTTCP-DIFFERENT-L1-NAT"))
{
	$testScript = "nested_kvm_ntttcp_different_l1_nat.sh"
}

function Start-TestExecution ($ip, $port, $cmd) {
	Write-LogInfo "Executing : ${cmd}"
	$testJob = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground
	while ((Get-Job -Id $testJob).State -eq "Running" ) {
		$currentStatus = Run-LinuxCmd -username $user -password $password -ip $ip -port $port -command "cat /home/$user/state.txt"
		Write-LogInfo "Current Test Status : $currentStatus"
		Wait-Time -seconds 20
	}
}

function Send-ResultToDatabase ($GlobalConfig, $logDir, $currentTestData) {
	Write-LogInfo "Uploading the test results.."
	$dataSource = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.server
	$user = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.user
	$password = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.password
	$database = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbname
	$dataTableName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbtable
	$TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
	if (!$TestCaseName) {
		$TestCaseName = $CurrentTestData.testName
	}
	if ($dataSource -And $user -And $password -And $database -And $dataTableName) {
		# Get host info
		$HostType = $global:TestPlatform
		$HostBy = $CurrentTestData.SetupConfig.TestLocation
		$HostOS = Get-Content "$LogDir\VM_properties.csv" | Select-String "Host Version"| ForEach-Object{$_ -replace ",Host Version,",""}

		# Get L1 guest info
		$L1GuestDistro = Get-Content "$LogDir\VM_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""}
		$L1GuestOSType = "Linux"
		$HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
		$L1GuestCpuNum = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.NumberOfCores
		$L1GuestMemMB = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.MemoryInMB

		$L1GuestSize = $L1GuestCpuNum.ToString() +"Cores "+($L1GuestMemMB/1024).ToString()+"G"
		$L1GuestKernelVersion = Get-Content "$LogDir\VM_properties.csv" | Select-String "Kernel version"| ForEach-Object{$_ -replace ",Kernel version,",""}

		# Get L2 guest info
		$L2GuestDistro = Get-Content "$LogDir\nested_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""}
		$L2GuestKernelVersion = Get-Content "$LogDir\nested_properties.csv" | Select-String "Kernel version"| ForEach-Object{$_ -replace ",Kernel version,",""}
		$flag=1
		if($CurrentTestData.SetupConfig.TestLocation.split(',').Length -eq 2)
		{
			$flag=0
		}

		if ($CurrentTestData.SetupConfig.SharedImageGallery) {
			$imageName = $CurrentTestData.SetupConfig.SharedImageGallery
		} else {
			$imageName = $CurrentTestData.SetupConfig.ARMImageName
		}

		foreach ( $param in $currentTestData.TestParameters.param)
		{
			if ($param -match "NestedCpuNum")
			{
				$L2GuestCpuNum = [int]($param.split("=")[1])
			}
			if ($param -match "NestedMemMB")
			{
				$L2GuestMemMB = [int]($param.split("=")[1])
			}
			if ($param -match "NestedNetDevice")
			{
				$KvmNetDevice = $param.split("=")[1]
			}
		}

		$IPVersion = "IPv4"
		$ProtocolType = "TCP"
		$connectionString = "Server=$dataSource;uid=$user; pwd=$password;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
		$LogContents = Get-Content -Path "$LogDir\report.log"
		$SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,ImageName,L1GuestOSType,L1GuestDistro,L1GuestSize,L1GuestKernelVersion,L2GuestDistro,L2GuestKernelVersion,L2GuestMemMB,L2GuestCpuNum,KvmNetDevice,IPVersion,ProtocolType,NumberOfConnections,Throughput_Gbps,Latency_ms,TestPlatform,DataPath,SameHost) VALUES "

		for($i = 1; $i -lt $LogContents.Count; $i++)
		{
			$Line = $LogContents[$i].Trim() -split '\s+'
			$SQLQuery += "('$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$imageName','$L1GuestOSType','$L1GuestDistro','$L1GuestSize','$L1GuestKernelVersion','$L2GuestDistro','$L2GuestKernelVersion','$L2GuestMemMB','$L2GuestCpuNum','$KvmNetDevice','$IPVersion','$ProtocolType',$($Line[0]),$($Line[1]),$($Line[2]),'$HostType','Synthetic','$flag'),"
		}
		$SQLQuery = $SQLQuery.TrimEnd(',')
		Write-LogInfo $SQLQuery

		$connection = New-Object System.Data.SqlClient.SqlConnection
		$connection.ConnectionString = $connectionString
		$connection.Open()

		$command = $connection.CreateCommand()
		$command.CommandText = $SQLQuery
		$command.executenonquery()
		$connection.Close()
		Write-LogInfo "Uploading the test results done!!"
	}
	else
	{
		Write-LogInfo "Database details are not provided. Results will not be uploaded to database!"
	}
}

function Main () {
	$currentTestResult = Create-TestResultObject
	$resultArr = @()
	$testResult = $resultAborted
	try
	{
		foreach($vm in $AllVMData)
		{
			if($vm.RoleName.Contains("role-0") -or $vm.RoleName.Contains("receiver"))
			{
				$hs1VIP = $vm.PublicIP
				$hs1vm1sshport = $vm.SSHPort
				$hs1secondip = $vm.SecondInternalIP
			}
			if($vm.RoleName.Contains("role-1") -or $vm.RoleName.Contains("sender"))
			{
				$hs2VIP = $vm.PublicIP
				$hs2vm1sshport = $vm.SSHPort
				$hs2secondip = $vm.SecondInternalIP
			}
		}
		Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames "none"
		if($TestPlatform -eq "Azure")
		{
			$cmd = "/home/$user/${testScript} -role server -clientIP $hs2secondip -serverIP $hs1secondip -level1ClientIP $hs2secondip -level1User root -level1Port 22 -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
			Start-TestExecution -ip $hs1VIP -port $hs1vm1sshport -cmd $cmd

			$cmd = "/home/$user/${testScript} -role client -clientIP $hs2secondip -serverIP $hs1secondip -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
			Start-TestExecution -ip $hs2VIP -port $hs2vm1sshport -cmd $cmd
		}
		elseif ($TestPlatform -eq "HyperV") {
			$cmd = "/home/$user/${testScript} -role server -level1ClientIP $hs2VIP -level1User root -level1Port $hs2vm1sshport -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
			Start-TestExecution -ip $hs1VIP -port $hs1vm1sshport -cmd $cmd

			$cmd = "/home/$user/${testScript} -role client -logFolder /home/$user > /home/$user/TestExecutionConsole.log"
			Start-TestExecution -ip $hs2VIP -port $hs2vm1sshport -cmd $cmd
		}

		# Download test logs
		Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$user/state.txt, /home/$user/${testScript}.log, /home/$user/TestExecutionConsole.log" -downloadTo $LogDir -port $hs2vm1sshport -username $user -password $password
		$finalStatus = Get-Content $LogDir\state.txt
		if ($finalStatus -imatch "TestFailed")
		{
			Write-LogErr "Test failed. Last known status : $currentStatus."
			$testResult = $resultFail
		}
		elseif ($finalStatus -imatch "TestAborted")
		{
			Write-LogErr "Test Aborted. Last known status : $currentStatus."
			$testResult = $resultAborted
		}
		elseif ($finalStatus -imatch "TestCompleted")
		{
			$testResult = $resultPass
		}
		elseif ($finalStatus -imatch "TestRunning")
		{
			Write-LogInfo "Powershell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
			$testResult = $resultAborted
		}

		Run-LinuxCmd -username $user -password $password -ip $hs2VIP -port $hs2vm1sshport -command ". utils.sh && collect_VM_properties" -runAsSudo
		Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$user/VM_properties.csv" -downloadTo $LogDir -port $hs2vm1sshport -username $user -password $password

		if ($testResult -imatch $resultPass)
		{
			Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$user/ntttcpConsoleLogs" -downloadTo $LogDir -port $hs2vm1sshport -username $user -password $password
			Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$user/nested_properties.csv, /home/$user/report.log" -downloadTo $LogDir -port $hs2vm1sshport -username $user -password $password
			Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$user/ntttcp-test-logs-receiver.tar, /home/$user/ntttcp-test-logs-sender.tar" -downloadTo $LogDir -port $hs2vm1sshport -username $user -password $password

			$ntttcpReportLog = Get-Content -Path "$LogDir\report.log"
			if (!$ntttcpReportLog)
			{
				$testResult = $resultFail
				throw "Invalid NTTTCP report file"
			}
			$uploadResults = $true
			$checkValues = "$resultPass,$resultFail,$resultAborted"
			foreach ( $line in $ntttcpReportLog ) {
				if ( $line -imatch "test_connections" ){
					continue;
				}
				try
				{
					$splits = $line.Trim() -split '\s+'
					$testConnections = $splits[0]
					$throughputGbps = $splits[1]
					$cyclePerByte = $splits[2]
					$averageTcpLatency = $splits[3]
					$metadata = "Connections=$testConnections"
					$connResult = "throughput=$throughputGbps`Gbps cyclePerBytet=$cyclePerByte Avg_TCP_lat=$averageTcpLatency"
					$currentTestResult.TestSummary +=  New-ResultSummary -testResult $connResult -metaData $metaData -checkValues $checkValues -testName $currentTestData.testName
					if ([string]$throughputGbps -imatch "0.00")
					{
						$testResult = $resultFail
						$uploadResults = $false
					}
				}
				catch
				{
					$currentTestResult.TestSummary +=  New-ResultSummary -testResult "Error in parsing logs." -metaData "NTTTCP" -checkValues $checkValues -testName $currentTestData.testName
				}
			}

			Write-LogInfo $currentTestResult.TestSummary
			if (!$uploadResults) {
				Write-LogInfo "Zero throughput for some connections, results will not be uploaded to database!"
			}
			else {
				Send-ResultToDatabase -GlobalConfig $GlobalConfig -logDir $LogDir -currentTestData $currentTestData
			}
		}
	}
	catch
	{
		$errorMessage =  $_.Exception.Message
		Write-LogInfo "EXCEPTION : $errorMessage"
	}

	$resultArr += $testResult
	Write-LogInfo "Test result : $testResult"
	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main
