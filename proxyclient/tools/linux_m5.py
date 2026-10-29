#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
import sys, pathlib
import serial
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

import argparse, pathlib

parser = argparse.ArgumentParser(description='(Linux) kernel loader for m1n1')
parser.add_argument('payload', type=pathlib.Path)
parser.add_argument('dtb', type=pathlib.Path)
parser.add_argument('initramfs', nargs='?', type=pathlib.Path)
parser.add_argument('--compression', choices=['auto', 'none', 'gz', 'xz'], default='auto')
parser.add_argument('-b', '--bootargs', type=str, metavar='"boot arguments"')
parser.add_argument('-t', '--tty', type=str)
parser.add_argument('-u', '--u-boot', type=pathlib.Path, help="load u-boot before linux")
parser.add_argument('-E', '--efi', action="store_true", help="payload is EFI stub (requires u-boot)")
parser.add_argument('-T', '--tso', action="store_true", help="enable TSO")
parser.add_argument('--reserve-ctrr-d', action=argparse.BooleanOptionalAction, default=True,
                    help="add the boot CPU's CTRR_D window as a /reserved-memory node "
                         "(default on; required for SMP on M5)")
parser.add_argument('--wdt', type=int, metavar='SECONDS', default=0,
                    help="arm the SoC watchdog (WD1, /arm-io/wdt) right before handoff so "
                         "the Mac resets itself if Linux hangs; Linux's apple_wdt keeps it "
                         "petted while the kernel is alive (0 = off)")
args = parser.parse_args()

from m1n1.setup import *
import subprocess

# M5: besides the CTRR_C window that m1n1 reserves ("M4+ SMP-RO"), the
# secondaries also write-protect the CTRR_D window just below m1n1's base.
# Linux allocating a page there and writing it from a secondary takes a
# permission fault on a writable PTE. The window moves with m1n1, so read it
# live and splice a reserved-memory node into the DTB before upload. Not
# no-map: Linux refuses a no-map node outright (-EBUSY) if any part of it is
# already reserved (e.g. by a /memreserve/ entry), which silently left the
# window allocatable in attempt 76. CTRR only blocks writes, so keeping the
# window in the linear map is harmless.
ctrr_d_window = None
def add_ctrr_d_reservation(dtb):
    global ctrr_d_window
    lwr = u.mrs((3, 0, 11, 0, 2))     # SYS_IMP_APL_CTRR_D_LWR_EL1
    upr = u.mrs((3, 0, 11, 0, 3))     # SYS_IMP_APL_CTRR_D_UPR_EL1
    if not lwr or upr < lwr:
        print("CTRR_D: not set (lwr=%#x upr=%#x), nothing reserved" % (lwr, upr))
        return dtb
    # UPR is the last protected 4K page (it ends right below m1n1's base);
    # round out to Linux's 16K pages.
    start = lwr & ~0x3fff
    end = (upr + 0x1000 + 0x3fff) & ~0x3fff
    print("CTRR_D: lwr=%#x upr=%#x -> reserving %#x..%#x (m1n1 base %#x)"
          % (lwr, upr, start, end, u.base))
    ctrr_d_window = (start, end)
    node = ("\t\tctrr-d@%x {\n\t\t\treg = <0x%x 0x%x 0x%x 0x%x>;\n\t\t};\n"
            % (start, start >> 32, start & 0xffffffff, (end - start) >> 32,
               (end - start) & 0xffffffff))
    dts = subprocess.run(["dtc", "-q", "-I", "dtb", "-O", "dts"], input=dtb,
                         capture_output=True, check=True).stdout.decode()
    anchor = "reserved-memory {\n\t\t#address-cells = <0x02>;\n\t\t#size-cells = <0x02>;\n\t\tranges;\n"
    if dts.count(anchor) != 1:
        raise Exception("CTRR_D: /reserved-memory node not found in DTB")
    dts = dts.replace(anchor, anchor + node)
    return subprocess.run(["dtc", "-q", "-I", "dts", "-O", "dtb"], input=dts.encode(),
                          capture_output=True, check=True).stdout

if args.efi and args.u_boot is None:
        raise Exception("Booting EFI stubs requires u-boot.")

if args.compression == 'auto':
    suffix = args.payload.suffix
    if args.efi:
        args.compression = 'none'
    elif suffix == '.gz':
        args.compression = 'gz'
    elif suffix == '.xz':
        args.compression = 'xz'
    else:
        raise ValueError('unknown compression for {}'.format(args.payload))

if args.tty is not None:
    tty_dev = serial.Serial(args.tty)
    tty_dev.reset_input_buffer()
    tty_dev.baudrate = 1500000
else:
    tty_dev = None

payload = args.payload.read_bytes()
dtb = args.dtb.read_bytes()
if args.reserve_ctrr_d:
    dtb = add_ctrr_d_reservation(dtb)
if args.initramfs is not None:
    initramfs = args.initramfs.read_bytes()
    initramfs_size = len(initramfs)
else:
    initramfs = None
    initramfs_size = 0

if args.bootargs is not None:
    print('Setting boot args: "{}"'.format(args.bootargs))
    p.kboot_set_chosen("bootargs", args.bootargs)

if args.compression != 'none':
    compressed_size = len(payload)
    compressed_addr = u.malloc(compressed_size)

    print("Loading %d bytes to 0x%x..0x%x..." % (compressed_size, compressed_addr, compressed_addr + compressed_size))
    iface.writemem(compressed_addr, payload, True)

dtb_addr = u.malloc(len(dtb))
print("Loading DTB to 0x%x..." % dtb_addr)

iface.writemem(dtb_addr, dtb)

kernel_size = 512 * 1024 * 1024
kernel_base = u.memalign(2 * 1024 * 1024, kernel_size)
boot_addr = kernel_base

print("Kernel_base: 0x%x" % kernel_base)

assert not (kernel_base & 0xffff)

if initramfs is not None:
    initramfs_base = u.memalign(65536, initramfs_size)
    print("Loading %d initramfs bytes to 0x%x..." % (initramfs_size, initramfs_base))
    iface.writemem(initramfs_base, initramfs, True)
    p.kboot_set_initrd(initramfs_base, initramfs_size)


if args.u_boot:
    uboot = bytearray(args.u_boot.read_bytes())
    uboot_size = len(uboot)
    uboot_addr = u.memalign(2*1024*1024, len(uboot))
    print("Loading u-boot to 0x%x..." % uboot_addr)

    u.compressed_writemem(uboot_addr, uboot, True)
    p.dc_cvau(uboot_addr, uboot_size)
    p.ic_ivau(uboot_addr, uboot_size)

    boot_addr = uboot_addr

    if args.efi and initramfs is not None:
        bootcmd = "bootefi 0x%x:0x%x 0x%x:0x%x $fdtcontroladdr" % (kernel_base, kernel_size, initramfs_base, initramfs_size)
    elif initramfs is not None:
        bootcmd = "booti 0x%x 0x%x:0x%x $fdtcontroladdr" % (kernel_base, initramfs_base, initramfs_size)
    elif args.efi:
        bootcmd = "bootefi 0x%x:0x%x $fdtcontroladdr" % (kernel_base, kernel_size)
    else:
        bootcmd = "booti 0x%x - $fdtcontroladdr" % (kernel_base)

    p.kboot_set_uboot("bootcmd", bootcmd)
    p.kboot_set_uboot("bootdelay", "0")

    if tty_dev is not None:
        p.kboot_set_uboot("baudrate", "%d" % tty_dev.baudrate)


p.cpufreq_init()
p.smp_start_secondaries()

if args.tso:
    print("Enabling TSO:")
    actlr = u.mrs("ACTLR_EL1")
    actlr |= (1 << 1) # TSO
    print("  CPU #0")
    u.msr("ACTLR_EL1", actlr)
    for i in range(1, 64):
        if p.smp_is_alive(i):
            print(f"  CPU #{i}")
            u.msr("ACTLR_EL1", actlr, call=lambda addr, *args: p.smp_call_sync(i, addr & ~REGION_RX_EL1, *args))
    p.kboot_set_chosen("apple,tso", "")

if p.kboot_prepare_dt(dtb_addr):
    print("DT prepare failed")
    sys.exit(1)

iface.dev.timeout = 40

if args.compression == 'none':
    kernel_size = len(payload)
    print("Loading %d bytes to 0x%x..0x%x..." % (kernel_size, kernel_base, kernel_base + kernel_size))
    iface.writemem(kernel_base, payload, True)
elif args.compression == 'gz':
    print("Uncompressing gz ...")
    kernel_size = p.gzdec(compressed_addr, compressed_size, kernel_base, kernel_size)
elif args.compression == 'xz':
    print("Uncompressing xz ...")
    kernel_size = p.xzdec(compressed_addr, compressed_size, kernel_base, kernel_size)
else:
    raise ValueError('unsupported compression {}'.format(args.compression))

print(kernel_size)

if kernel_size < 0:
    raise Exception("Decompression error!")

print("Decompress OK...")

p.dc_cvau(kernel_base, kernel_size)
p.ic_ivau(kernel_base, kernel_size)

print("Ready to boot")

daif = u.mrs(DAIF)
daif = 0xc0
u.msr(DAIF, daif)
print("DAIF: %x" % daif)

# M5 (T8142): kboot_boot() faults in dapf_init_all() (shared DAPF block at
# 0x380714000 SErrors on write), so do its job by hand without that step.
# kboot_prepare_dt() left the final DT in m1n1's heap; find it by its FDT
# magic plus its first memreserve entry, which covers the DT buffer itself.
def find_prepared_dt():
    start = u.heap_base - 128 * 1024 * 1024    # m1n1's own heap (see ProxyUtils)
    for addr in range(start, u.heap_base, 16384):
        if p.read32(addr) != 0xedfe0dd0:       # 0xd00dfeed, big-endian
            continue
        off_rsv = int.from_bytes(iface.readmem(addr + 16, 4), "big")
        if int.from_bytes(iface.readmem(addr + off_rsv, 8), "big") == addr:
            return addr
    raise Exception("prepared DT not found in m1n1 heap")

dt_final = find_prepared_dt()
print("Prepared DT at 0x%x" % dt_final)
# Audit the exact blob passed in x0, rather than relying on preparation logs.
from fdt_bootargs import bootargs_from_fdt
dt_size = int.from_bytes(iface.readmem(dt_final + 4, 4), "big")
if not 40 <= dt_size <= 2 * 1024 * 1024:
    raise ValueError("Implausible prepared FDT size")
final_bootargs = bootargs_from_fdt(iface.readmem(dt_final, dt_size))
print("Verified prepared FDT bootargs: " + repr(final_bootargs))
if args.bootargs is not None:
    expected_bootargs = args.bootargs + " idle=nop arm64.nowfxt"
    if final_bootargs != expected_bootargs:
        raise ValueError("Prepared M5 FDT bootargs differ from requested + m1n1 overrides")
if ctrr_d_window is not None:
    from fdt_bootargs import reservations_from_fdt
    rsv, nodes = reservations_from_fdt(iface.readmem(dt_final, dt_size))
    ws, we = ctrr_d_window
    for a, l in rsv:
        if a < we and a + l > ws:
            print("CTRR_D: overlapping /memreserve/ %#x..%#x" % (a, a + l))
    mine = [n for n in nodes if n[0].startswith("ctrr-d@")]
    if len(mine) != 1 or mine[0][1] != [(ws, we - ws)] or mine[0][2]:
        raise ValueError("CTRR_D reservation missing/wrong in prepared FDT: %r" % (mine,))
    print("CTRR_D: verified in prepared FDT: %s reg %#x+%#x" % (mine[0][0], ws, we - ws))
if args.wdt:
    # Same WD1 registers m1n1's wdt_reboot() and Linux's apple_wdt use
    # (CUR_TIME 0x10, BITE_TIME 0x14, CTRL 0x1c, RESET_EN bit 2), 24 MHz clkref.
    # apple_wdt sees RESET_EN at probe, marks it running and reloads a 30 s
    # timeout that the watchdog core then pets, so this only fires on a hang
    # (before probe: after args.wdt s; after probe: ~30 s after the hang).
    wdt_base = u.adt["/arm-io/wdt"].get_reg(0)[0]
    if wdt_base != 0x3882b0000:    # J704 value, matches dts/t8142.dtsi watchdog@
        raise ValueError("unexpected WDT base %#x" % wdt_base)
    if not 1 <= args.wdt <= 170:
        raise ValueError("--wdt must be 1..170 s (32-bit counter at 24 MHz)")
    p.write32(wdt_base + 0x1c, 0)
    p.write32(wdt_base + 0x14, args.wdt * 24000000)
    p.write32(wdt_base + 0x10, 0)
    p.write32(wdt_base + 0x1c, 4)
    print("WDT: armed WD1 @ %#x for %d s (ctrl=%#x bite=%#x)" % (
        wdt_base, args.wdt, p.read32(wdt_base + 0x1c), p.read32(wdt_base + 0x14)))
p.smp_set_wfe_mode(True)
print("Vectoring to kernel at 0x%x" % boot_addr)
p.request(p.P_VECTOR, boot_addr, dt_final)

iface.ttymode(tty_dev)
