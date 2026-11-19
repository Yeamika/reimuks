#!/usr/bin/env python3
"""Run the actual watchdog shell against a PTY and a harmless reboot recorder."""
import os,pty,shutil,signal,subprocess,tempfile,time
from pathlib import Path
script=Path(__file__).resolve().parents[1]/'initramfs/rootfs/bin/polaris-boot-watchdog'
build=Path(os.environ['POLARIS_WATCHDOG_TEST_ROOT']).resolve();build.mkdir(parents=True,exist_ok=True)
def case(name,budget,lease,kind):
 with tempfile.TemporaryDirectory(prefix=name+'-',dir=build) as temp:
  root=Path(temp);state=root/'state';mock=root/'bin';mock.mkdir()
  reboot=mock/'reboot';reboot.write_text('#!/bin/sh\nprintf reboot >"$POLARIS_WATCHDOG_STATE_DIR/rebooted"\n');reboot.chmod(0o755)
  cmdline=root/'cmdline';cmdline.write_text(f'reimuks.watchdog={budget} reimuks.watchdog.lease={lease}\n')
  master,slave=pty.openpty();env=dict(os.environ,POLARIS_WATCHDOG_STATE_DIR=str(state),POLARIS_WATCHDOG_DEVICE=os.ttyname(slave),POLARIS_WATCHDOG_CMDLINE=str(cmdline),PATH=str(mock)+':/usr/bin:/bin')
  group=None
  def call(command):subprocess.run(['sh',str(script),command],env=env,check=True)
  try:
   proc=subprocess.Popen(['sh',str(script),'start'],env=env,start_new_session=True)
   group=proc.pid;assert proc.wait(timeout=6)==0;assert (state/'armed').exists()
   start=time.monotonic()
   if kind=='stale':
    while time.monotonic()-start<5 and not (state/'rebooted').exists():time.sleep(.1)
    assert (state/'rebooted').exists(),'a stalled init did not request recovery'
   elif kind=='budget':
    while time.monotonic()-start<budget+2 and not (state/'rebooted').exists():call('tick');time.sleep(.3)
    assert (state/'rebooted').exists(),'progress incorrectly bypassed the boot deadline'
   else:
    while time.monotonic()-start<budget-1:call('tick');time.sleep(.3)
    assert not (state/'rebooted').exists()
    call('ready')
    while time.monotonic()-start<budget+2:call('tick');time.sleep(.3)
    assert not (state/'rebooted').exists(),'a ready initramfs incorrectly hit the boot deadline'
    call('handoff');assert not (state/'armed').exists()
    os.set_blocking(master,False);data=os.read(master,4096)
    assert b'V' not in data and data.endswith(b'.') and data.count(b'.')>=budget,'watchdog was disabled during rootfs handoff'
   print(name,'passed',round(time.monotonic()-start,2),flush=True)
  finally:
   if group:
    try:os.killpg(group,signal.SIGKILL)
    except ProcessLookupError:pass
   os.close(master);os.close(slave)
case('progress-stall',180,2,'stale')
case('total-boot-deadline',5,3,'budget')
case('continued-progress-and-handoff',6,3,'healthy')
