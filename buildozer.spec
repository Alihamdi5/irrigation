[app]
title = Smart Irrigation
package.name = smartirrigation
package.domain = org.hamdi
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
version = 0.1

# اضافه شدن pyjnius برای رفع خطا
requirements = python3,kivy,pyjnius,sqlalchemy,jdatetime,arabic-reshaper,python-bidi

orientation = portrait
fullscreen = 0

# فعال‌سازی مجوز اینترنت
android.permissions = INTERNET

android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True
android.release_artifact = aab
android.debug_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1

# فعال‌سازی تنظیمات p4a برای جلوگیری از خطای بیلد
p4a.setup_py = false
