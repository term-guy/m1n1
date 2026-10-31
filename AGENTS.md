# term-guy/m1n1 — M5 (T8142) bring-up fork

This is **termg's personal fork** of [AsahiLinux/m1n1](https://github.com/AsahiLinux/m1n1),
used to bring up Linux on an Apple M5 MacBook Pro 14" (Mac17,2, board J704, SoC T8142).

## Upstream policy (read first)

The upstream m1n1 maintainers forbid any use of AI or LLM tools on their project for legal
reasons (https://asahilinux.org/slop/). That policy is theirs and stays in force for upstream.
In **this fork only**, the owner has chosen to use LLM assistance. Therefore:

- Never submit, propose, or mail changes from this fork to upstream Asahi m1n1, and never
  present them as Asahi work. Anything meant for upstream must be rewritten by a human under
  upstream's rules.
- Every commit made with LLM help carries the trailer `Assisted-By: LLM`.
- Commit author: `termg <hello@termg.com>`. Commit, push or open PRs only when the owner
  asks.

## Branches

- `main`: upstream mirror. Do not commit here.
- `m5-dev`: 33c235dd + `dapf: Skip DAPF init on T8142` + `proxyclient: tools: Add
  linux_m5.py loader for M5 (T8142) bring-up` (host-side proxy loader).
- `m5-standalone`: work towards booting Linux from m1n1 without the host (T8142 only): program
  only dart-mtp's DAPF, reserve the CTRR_D window, skip the untested mcc/tunables/clk/usb/pcie
  kboot steps, arm the WDT before hand-off.
- `m5-hv`: hypervisor test branch for running macOS under m1n1 on T8142 (tracing hardware,
  e.g. GPU firmware messages): upstream `main` (SPTM/TXM hypervisor) + the `m5-standalone`
  commits + T8142 hypervisor fixes (VREG, AMCC enable mask, CTRR D EL2 readback). Chainloaded
  as a raw `.bin` from the stage-1 proxy, never installed as stage 1.

The Mac runs an installed m1n1 built from 33c235dd (`33c235dd-dirty`). Keep the proxy client
compatible with it.

## Build

Needs clang/lld (or the aarch64 GNU toolchain) and Rust with the
`aarch64-unknown-none-softfloat` target (`rustup target add aarch64-unknown-none-softfloat`).
`make -j$(nproc)` produces `build/m1n1.bin` and `build/m1n1.macho`; `tools/chainload.py` needs
the `.macho`.

## Rules for work on this fork

- **Do not install or flash m1n1 on the Mac** (`kmutil configure-boot`, boot policy changes)
  without the owner's explicit go-ahead. Test new builds by chainloading over the proxy first.
- **Clean room:** never disassemble, decompile or decode Apple binaries. ADT data and register
  probing through the m1n1 proxy are fine. Apple firmware blobs may only be passed through
  unmodified (e.g. asahi-installer's converter output), never analysed.
- **Privacy:** ADT dumps contain the Mac's serial numbers, MAC addresses and ECID. Never commit
  or publish them, or any Apple firmware.
- Keep T8142-specific changes behind `chip_id == T8142` so other SoCs behave as upstream.

The bring-up log, host tools and hand-off notes live outside this repository (the `m5-j704`
kit: `HANDOFF.md`, `LOG.md`).
