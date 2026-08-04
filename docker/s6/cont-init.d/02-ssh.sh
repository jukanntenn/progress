#!/bin/sh
mkdir -p ~/.ssh
chmod 700 ~/.ssh
git config --global core.sshCommand 'ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=~/.ssh/known_hosts'
echo "[cont-init.d] SSH client configured"
