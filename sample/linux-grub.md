# GRUB Rescue Troubleshooting

Notes from fixing a machine that dropped to a `grub rescue>` prompt after a
failed kernel update.

## What happened

After a routine `apt upgrade` that pulled in a new kernel, the machine
rebooted straight into a `grub rescue>` shell instead of the boot menu.
`ls` at the rescue prompt showed `(hd0)`, `(hd0,gpt1)`, and `(hd0,gpt2)` but
none of the normal partition labels.

## Root cause

The upgrade had regenerated `/boot/grub/grub.cfg` but the `grub-pc` package
failed to reinstall the boot sector on `/dev/sda`, so the MBR/EFI entry was
still pointing at boot files that no longer matched the on-disk layout. GRUB
loads in two stages: a tiny first-stage loader embedded in the disk's boot
sector, then a second stage that reads `grub.cfg` from `/boot/grub/`. The
first stage was stale, so it couldn't even find the second stage.

## GRUB rescue

At the rescue prompt, the fix was:

```
grub rescue> ls
grub rescue> set root=(hd0,gpt2)
grub rescue> set prefix=(hd0,gpt2)/boot/grub
grub rescue> insmod normal
grub rescue> normal
```

That got back to a full GRUB shell, from which the system could boot far
enough to run `grub-install /dev/sda` and `update-grub` properly from a live
environment.

## Prevention

`update-grub` regenerates `grub.cfg`, but it does **not** reinstall the boot
sector - that only happens via `grub-install`. After any kernel or disk
layout change, run both, not just one.
