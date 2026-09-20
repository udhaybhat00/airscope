# Driver Credits

airscope's userland drivers are Python re-implementations of **GPLv2 Linux kernel and vendor DKMS drivers**.

Supported chipsets:

- RTL8188EUS, RTL8812AU, RTL8821AU, RTL8814AU, RTL8822BU, RTL8922AU
- RT2500USB, RT2800USB, RT3070, RT5370, RT5372, RT5572
- MT7610U, MT7612U, MT7921AU, MT7925U
- AR9271, RTL8187

These implementations are derived from upstream open-source Linux wireless drivers
(`drivers/net/wireless/` — rt2x00, mt76, ath9k, rtl818x, rtw88 trees) and out-of-tree
vendor DKMS sources. Firmware blobs remain under their respective vendor licenses
(see `docs/FIRMWARE.md`).

> **Maintainers:** when a new chipset is ported, update this file. See
> `docs/porting/METHODOLOGY.md` → "Housekeeping".
