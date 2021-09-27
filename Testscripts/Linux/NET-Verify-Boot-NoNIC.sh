#!/bin/bash

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    exit 0
}
# Source constants file and initialize most common variables
UtilsInit

# detect the architecture
uname -a | grep x86_64
if [ $? -eq 0 ]; then
    LogMsg "64 bit architecture was detected"
    kvp_client="kvp_client64"
else
    uname -a | grep i686
    if [ $? -eq 0 ]; then
        LogMsg "32 bit architecture was detected"
        kvp_client="kvp_client32"
    else
        uname -a | grep aarch64
        if [ $? -eq 0 ]; then
            LogMsg "arm 64 bit architecture was detected"
            kvp_client="kvp_client_arm64"
        else
            LogErr "Unable to detect OS architecture"
            SetTestStateAborted
            exit 0
        fi
    fi
fi

if [ ! -e ${kvp_client} ]; then
    echo "the file kvp_client does not exist"
    exit 0
fi

chmod 755 ./kvp_client*

# Verify there are no eth devices
echo "Check count of eth devices"
ethCount=$(ls -d /sys/class/net/eth* | wc -l)
echo "ethCount = ${ethCount}"
if [ $ethCount -ne 0 ]; then
    echo "eth device count is not zero: ${ethCount}"
    exit 0
fi

# Create a nonintrinsic HotAddTest KVP item with a value of 'NoNICs'
echo "Creating HotAddTest key with value of 'NoNICS'"
./$kvp_client append 1 'HotAddTest' 'NoNICs'

# Loop waiting for an eth device to appear
echo "Waiting for an eth device to appear"
timeout=300
noEthDevice=1
while [ $noEthDevice -eq 1 ]
do
    ethCount=$(ls -d /sys/class/net/eth* | wc -l)
    if [[ $ethCount -eq 1 ]]; then
        echo "An eth device was detected"
        break
    fi

    timeout=$((timeout-10))
    sleep 10
    if [ $timeout -le 0 ]; then
        echo "Timed out waiting for eth device to be created"
        exit 0
    fi
done

# Bring up the new eth device
ifup eth0
sleep 60

# Verify the eth device received an IP address
echo "Verify the new NIC received an IPv4 address"
ip addr show eth0 | grep "inet\b"
if [ $? -ne 0 ]; then
    echo "eth0 was not assigned an IPv4 address"
    exit 0
fi

echo "eth0 is up"

# Modify the KVP HotAddTest value to 'NICUp'
echo "Updating HotAddTest KVP item to 'NICUp'"
./$kvp_client append 1 'HotAddTest' 'NICUp'

# Loop waiting for the eth device to be removed
echo "Waiting for the eth device to be deleted"
timeout=300
noEthDevice=1
while [ $noEthDevice -eq 1 ]
do
    ethCount=$(ls -d /sys/class/net/eth* | wc -l)
    if [ $ethCount -eq 0 ]; then
        echo "eth count is zero"
        break
    fi

    timeout=$((timeout-10))
    sleep 10
    if [ $timeout -le 0 ]; then
        echo "Timed out waiting for eth device to be hot removed"
        exit 0
    fi
done

# Modify the KVP HotAddTest value to 'NoNICs'
echo "Setting HotAddTest value to 'NoNICs'"
./$kvp_client append 1 'HotAddTest' 'NoNICs'
echo "Test complete - exiting"
exit 0