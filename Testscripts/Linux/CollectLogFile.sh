#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

while echo $1 | grep ^- > /dev/null; do
        eval $( echo $1 | sed 's/-//g' | tr -d '\012')=$2
        shift
        shift
done

if [ -z "$hostname" ]; then
        hostname=$(hostname)
fi
export PATH="/sbin:/bin:/usr/sbin:/usr/bin"
sudo dmesg > ${hostname}-dmesg.txt
cp /var/log/waagent.log ${hostname}-waagent.log.txt
uname -r > ${hostname}-kernelVersion.txt
uname -i > ${hostname}-hardwarePlatform.txt
system_start=$(uptime -s || last reboot -F | head -1 | awk '{print $9,$6,$7,$8}')
echo $system_start > ${hostname}-uptime.txt || echo "UPTIME_COMMAND_ERROR" > ${hostname}-uptime.txt
modinfo hv_netvsc > ${hostname}-lis.txt
release=$(cat /etc/*release*)
if [ -f /etc/redhat-release ] ; then
        echo "/etc/redhat-release detected"
        if [[ "$release" =~ "Oracle" ]] ; then
                cat /etc/os-release | grep ^PRETTY_NAME | sed 's/"//g' | sed 's/PRETTY_NAME=//g' > ${hostname}-distroVersion.txt
        else
                cat /etc/redhat-release > ${hostname}-distroVersion.txt
        fi
elif [ -f /etc/SuSE-release ] ; then
        echo "/etc/SuSE-release detected"
        cat /etc/os-release | grep ^PRETTY_NAME | sed 's/"//g' | sed 's/PRETTY_NAME=//g' > ${hostname}-distroVersion.txt
elif [[ "$release" =~ "UBUNTU" ]] || [[ "$release" =~ "Ubuntu" ]] || [[ "$release" =~ "Debian" ]] || \
            [[ "$release" =~ "SUSE Linux Enterprise Server 15" ]] || [[ "$release" =~ "CoreOS" ]] || [[ "$release" =~ "Mariner" ]]; then
        NAME=$(cat /etc/os-release | grep ^NAME= | sed 's/"//g' | sed 's/NAME=//g')
        VERSION=$(cat /etc/os-release | grep ^VERSION= | sed 's/"//g' | sed 's/VERSION=//g')
        echo "$NAME $VERSION" > ${hostname}-distroVersion.txt
elif [ -e /usr/share/clear/version ]; then
        NAME=$(cat /usr/lib/os-release | grep ^PRETTY_NAME | sed 's/"//g' | sed 's/PRETTY_NAME=//g')
        VERSION=$(cat /usr/lib/os-release | grep ^VERSION= | sed 's/"//g' | sed 's/VERSION=//g')
        echo "$NAME $VERSION" > ${hostname}-distroVersion.txt
else
        echo "unknown" > ${hostname}-distroVersion.txt
        echo $release > ${hostname}-unknownDistro.txt
fi
exit 0
