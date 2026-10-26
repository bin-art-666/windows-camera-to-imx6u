@echo off
setlocal
cd /d "%~dp0"
echo Deploying receiver to root@192.168.1.4 ...
ssh -o HostKeyAlgorithms=+ssh-rsa root@192.168.1.4 "mkdir -p /home/root/camera_transport"
if errorlevel 1 goto failed
scp -O -o HostKeyAlgorithms=+ssh-rsa "%~dp0receiver.py" root@192.168.1.4:/home/root/camera_transport/receiver.py
if errorlevel 1 goto failed
ssh -t -o HostKeyAlgorithms=+ssh-rsa root@192.168.1.4 "cd /home/root/camera_transport && python3 -u receiver.py --output /tmp/camera_latest.jpg"
exit /b %ERRORLEVEL%
:failed
echo Deployment failed. Check the network and SSH output above.
pause
exit /b 1
