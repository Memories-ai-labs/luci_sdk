from luci.luci import LUCI

luci = LUCI.connect_via_adb()
# luci.join_hotspot("<HOTSPOT-NAME>", "<HOTSPOT-PASSWORD>")
luci.join_hotspot("DESKTOP-SOI3AJP", "7U1640ab")

print(luci.device.storage())
print(luci.device.config())

luci.view_stream()
