from waveshare_epd import epd2in13_V3 as epd_driver  # or your variant
epd = epd_driver.EPD()
epd.init("full")
epd.Clear(0xFF)
epd.sleep()
