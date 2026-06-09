import os
import sys
import traceback

import jdatetime
import arabic_reshaper
from bidi.algorithm import get_display

from sqlalchemy import create_engine, Column, Integer, String, Float, UniqueConstraint
from sqlalchemy.orm import sessionmaker, declarative_base

from kivy.app import App
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.properties import StringProperty
from kivy.graphics import Color, RoundedRectangle

# -------------------------
# Paths / Constants
# -------------------------
def get_app_dir():
    if sys.platform == "android":
        try:
            from android.storage import app_storage_path
            return app_storage_path()
        except Exception:
            return os.getcwd()
    return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()
DB_PATH = os.path.join(APP_DIR, "smart_irrigation_mobile.db")
FONT_PATH = "Vazir-Black.ttf"

# -------------------------
# Database
# -------------------------
Base = declarative_base()
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine)

class Farm(Base):
    __tablename__ = "farms"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    area = Column(Float, default=0)
    target_cpe = Column(Float, default=0)
    last_irrigation = Column(String, nullable=False)  # Jalali YYYY/MM/DD

class Evaporation(Base):
    __tablename__ = "evaporation"
    id = Column(Integer, primary_key=True)
    date = Column(String, nullable=False, unique=True)  # Jalali YYYY/MM/DD
    evap = Column(Float, default=0)
    __table_args__ = (UniqueConstraint("date", name="uq_evap_date"),)

Base.metadata.create_all(engine)

# -------------------------
# Persian helpers
# -------------------------
def fa(text: str) -> str:
    s = "" if text is None else str(text)
    try:
        return get_display(arabic_reshaper.reshape(s))
    except Exception:
        return s

def today_jalali() -> str:
    return jdatetime.date.today().strftime("%Y/%m/%d")

def jalali_to_gregorian(jdate_str: str):
    try:
        y, m, d = map(int, jdate_str.split("/"))
        return jdatetime.date(y, m, d).togregorian()
    except Exception:
        return None

def parse_float(s, default=0.0):
    try:
        if s is None:
            return default
        s = str(s).strip()
        if s == "":
            return default
        return float(s)
    except Exception:
        return default

def safe_date_str(s):
    s = (s or "").strip()
    if len(s) != 10 or s.count("/") != 2:
        return None
    try:
        y, m, d = map(int, s.split("/"))
        jdatetime.date(y, m, d)
        return s
    except Exception:
        return None

# -------------------------
# Calculations
# -------------------------
def calc_farm_metrics(db, farm: Farm):
    last_g = jalali_to_gregorian(farm.last_irrigation)
    if not last_g:
        return 0.0, 0.0, "نامشخص", (0.5, 0.5, 0.5, 1), fa("تاریخ آخرین آبیاری نامعتبر است")

    evaps = db.query(Evaporation).all()
    cum = 0.0
    for e in evaps:
        g = jalali_to_gregorian(e.date)
        if g and g >= last_g:
            cum += float(e.evap or 0)

    target = float(farm.target_cpe or 0)
    percent = (cum / target * 100.0) if target > 0 else 0.0

    if target <= 0:
        return round(cum, 1), 0.0, "بدون هدف", (0.35, 0.35, 0.35, 1), fa("هدف CPE تعریف نشده است")

    if percent < 75:
        return round(cum, 1), round(percent, 1), "ایمن", (0.10, 0.65, 0.30, 1), fa("وضعیت مناسب است")
    elif percent < 100:
        return round(cum, 1), round(percent, 1), "هشدار", (1.00, 0.60, 0.00, 1), fa("نزدیک به آستانه آبیاری")
    else:
        return round(cum, 1), round(percent, 1), "بحرانی", (0.90, 0.15, 0.15, 1), fa("نیاز فوری به آبیاری")

# -------------------------
# UI helpers
# -------------------------
def show_popup(title_fa, msg_fa):
    content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))

    lbl = Label(
        text=msg_fa,
        font_name=FONT_PATH,
        color=(0, 0, 0, 1),
        halign="right",
        valign="middle",
    )
    content.add_widget(lbl)

    btn = Button(
        text=fa("باشه"),
        font_name=FONT_PATH,
        size_hint_y=None,
        height=dp(44),
        background_normal="",
        background_color=(0.15, 0.35, 0.75, 1),
    )
    content.add_widget(btn)

    pop = Popup(
        title=title_fa,
        content=content,
        size_hint=(0.88, None),
        height=dp(260),
    )
    btn.bind(on_release=pop.dismiss)
    pop.open()

class Card(BoxLayout):
    def __init__(self, bg=(1, 1, 1, 1), radius=14, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*bg)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size

# -------------------------
# Screens
# -------------------------
class DashboardScreen(Screen):
    banner_text = StringProperty("")

    def on_enter(self):
        Clock.schedule_once(self.refresh, 0.05)

    def refresh(self, *_):
        db = SessionLocal()
        try:
            farms = db.query(Farm).order_by(Farm.id.desc()).all()

            total_farms = len(farms)
            critical = 0
            total_cum = 0.0
            banner = ""

            self.ids.farms_container.clear_widgets()

            for farm in farms:
                cum, pct, status_raw, color, warn = calc_farm_metrics(db, farm)
                total_cum += cum

                if status_raw == "بحرانی":
                    critical += 1
                    if not banner:
                        banner = App.get_running_app().fa("هشدار: برخی مزارع بحرانی هستند — آبیاری را بررسی کنید")
                elif status_raw == "هشدار" and not banner:
                    banner = App.get_running_app().fa("توجه: برخی مزارع نزدیک آستانه آبیاری هستند")

                card = Card(
                    bg=(0.96, 0.97, 0.99, 1),
                    size_hint_y=None,
                    height=dp(132),
                    padding=dp(10),
                    spacing=dp(6),
                    orientation="vertical",
                )

                top = BoxLayout(size_hint_y=None, height=dp(34))
                name_lbl = Label(text=fa(farm.name), font_name=FONT_PATH, color=(0, 0, 0, 1), halign="right")
                pct_lbl = Label(text=f"{pct:.1f}%", font_name=FONT_PATH, color=color, size_hint_x=None, width=dp(90))
                top.add_widget(pct_lbl)
                top.add_widget(name_lbl)

                mid = Label(
                    text=fa(f"تبخیر تجمعی: {cum:.1f} میلی‌متر   |   هدف: {float(farm.target_cpe or 0):.1f}"),
                    font_name=FONT_PATH,
                    color=(0.25, 0.25, 0.25, 1),
                    halign="right",
                )

                status_lbl = Label(
                    text=fa(f"وضعیت: {status_raw}"),
                    font_name=FONT_PATH,
                    color=color,
                    halign="right",
                )
                last_lbl = Label(
                    text=fa(f"آخرین آبیاری: {farm.last_irrigation}"),
                    font_name=FONT_PATH,
                    color=(0.25, 0.25, 0.25, 1),
                    halign="right",
                )

                bot = BoxLayout(size_hint_y=None, height=dp(28))
                bot.add_widget(status_lbl)
                bot.add_widget(last_lbl)

                card.add_widget(top)
                card.add_widget(mid)
                card.add_widget(bot)

                self.ids.farms_container.add_widget(card)

            self.banner_text = banner

            self.ids.kpi_total.text = App.get_running_app().fa("کل مزارع")
            self.ids.kpi_total_val.text = str(total_farms)

            self.ids.kpi_critical.text = App.get_running_app().fa("بحرانی")
            self.ids.kpi_critical_val.text = str(critical)

            self.ids.kpi_cum.text = App.get_running_app().fa("تبخیر تجمعی")
            self.ids.kpi_cum_val.text = f"{total_cum:.1f} mm"

        except Exception as e:
            print("Dashboard refresh error:", e)
            traceback.print_exc()
            show_popup(fa("خطا"), fa(str(e)))
        finally:
            db.close()

class FarmsScreen(Screen):
    selected_id = None

    def on_enter(self):
        Clock.schedule_once(self.refresh_list, 0.05)
        self.ids.in_last.text = today_jalali()

    def clear_form(self):
        self.selected_id = None
        self.ids.in_name.text = ""
        self.ids.in_area.text = ""
        self.ids.in_cpe.text = ""
        self.ids.in_last.text = today_jalali()
        self.ids.btn_save.text = App.get_running_app().fa("ذخیره (افزودن)")
        self.ids.btn_delete.disabled = True
        self.ids.btn_reset.disabled = True

    def refresh_list(self, *_):
        self.ids.list_container.clear_widgets()
        db = SessionLocal()
        try:
            farms = db.query(Farm).order_by(Farm.id.desc()).all()

            for farm in farms:
                row = Card(bg=(1, 1, 1, 1), size_hint_y=None, height=dp(64),
                           padding=dp(10), orientation="horizontal", spacing=dp(8))

                info = Label(
                    text=fa(f"{farm.name}  |  {float(farm.area or 0):.2f} هکتار  |  CPE هدف: {float(farm.target_cpe or 0):.1f}"),
                    font_name=FONT_PATH,
                    color=(0, 0, 0, 1),
                    halign="right",
                )

                btn = Button(
                    text=fa("انتخاب"),
                    font_name=FONT_PATH,
                    size_hint_x=None,
                    width=dp(90),
                    background_normal="",
                    background_color=(0.15, 0.35, 0.75, 1),
                )
                btn.bind(on_release=lambda _btn, fid=farm.id: self.load_farm(fid))

                row.add_widget(btn)
                row.add_widget(info)
                self.ids.list_container.add_widget(row)

            if self.selected_id is None:
                self.clear_form()

        except Exception as e:
            print("Farms refresh_list error:", e)
            traceback.print_exc()
            show_popup(fa("خطا"), fa(str(e)))
        finally:
            db.close()

    def load_farm(self, farm_id):
        db = SessionLocal()
        try:
            farm = db.query(Farm).filter(Farm.id == farm_id).first()
            if not farm:
                return

            self.selected_id = farm.id
            self.ids.in_name.text = farm.name
            self.ids.in_area.text = str(farm.area or 0)
            self.ids.in_cpe.text = str(farm.target_cpe or 0)
            self.ids.in_last.text = farm.last_irrigation
            self.ids.btn_save.text = App.get_running_app().fa("ذخیره (ویرایش)")
            self.ids.btn_delete.disabled = False
            self.ids.btn_reset.disabled = False

        except Exception as e:
            print("Load farm error:", e)
            traceback.print_exc()
            show_popup(fa("خطا"), fa(str(e)))
        finally:
            db.close()

    def save(self):
        try:
            name = (self.ids.in_name.text or "").strip()
            if not name:
                show_popup(fa("خطا"), fa("نام مزرعه را وارد کنید."))
                return

            area = parse_float(self.ids.in_area.text, 0.0)
            cpe = parse_float(self.ids.in_cpe.text, 0.0)
            last = safe_date_str(self.ids.in_last.text)
            if not last:
                show_popup(fa("خطا"), fa("تاریخ آخرین آبیاری باید به شکل 1403/01/01 باشد."))
                return

            db = SessionLocal()
            try:
                if self.selected_id is None:
                    db.add(Farm(name=name, area=area, target_cpe=cpe, last_irrigation=last))
                else:
                    farm = db.query(Farm).filter(Farm.id == self.selected_id).first()
                    if not farm:
                        show_popup(fa("خطا"), fa("مزرعه پیدا نشد."))
                        return
                    farm.name = name
                    farm.area = area
                    farm.target_cpe = cpe
                    farm.last_irrigation = last
                db.commit()
            finally:
                db.close()

            self.refresh_list()
            App.get_running_app().root.get_screen("dash").refresh()
            show_popup(fa("انجام شد"), fa("اطلاعات مزرعه ذخیره شد."))

        except Exception as e:
            print("Farm save error:", e)
            traceback.print_exc()
            show_popup(fa("خطای برنامه"), fa(str(e)))

    def delete(self):
        try:
            if self.selected_id is None:
                return

            db = SessionLocal()
            try:
                db.query(Farm).filter(Farm.id == self.selected_id).delete()
                db.commit()
            finally:
                db.close()

            self.clear_form()
            self.refresh_list()
            App.get_running_app().root.get_screen("dash").refresh()
            show_popup(fa("انجام شد"), fa("مزرعه حذف شد."))

        except Exception as e:
            print("Farm delete error:", e)
            traceback.print_exc()
            show_popup(fa("خطای برنامه"), fa(str(e)))

    def restart_irrigation(self):
        try:
            if self.selected_id is None:
                return

            db = SessionLocal()
            try:
                farm = db.query(Farm).filter(Farm.id == self.selected_id).first()
                if not farm:
                    show_popup(fa("خطا"), fa("مزرعه پیدا نشد."))
                    return
                farm.last_irrigation = today_jalali()
                db.commit()
            finally:
                db.close()

            self.load_farm(self.selected_id)
            App.get_running_app().root.get_screen("dash").refresh()
            show_popup(fa("انجام شد"), fa("چرخه آبیاری از امروز شروع شد."))

        except Exception as e:
            print("Restart irrigation error:", e)
            traceback.print_exc()
            show_popup(fa("خطای برنامه"), fa(str(e)))

class EvapScreen(Screen):
    selected_id = None

    def on_enter(self):
        self.ids.e_date.text = today_jalali()
        Clock.schedule_once(self.refresh_list, 0.05)

    def clear_form(self):
        self.selected_id = None
        self.ids.e_date.text = today_jalali()
        self.ids.e_val.text = ""
        self.ids.e_save.text = App.get_running_app().fa("ذخیره (افزودن/به‌روزرسانی)")
        self.ids.e_delete.disabled = True

    def refresh_list(self, *_):
        self.ids.e_container.clear_widgets()
        db = SessionLocal()
        try:
            rows = db.query(Evaporation).order_by(Evaporation.date.desc()).all()

            for e in rows:
                row = Card(bg=(1, 1, 1, 1), size_hint_y=None, height=dp(58),
                           padding=dp(10), orientation="horizontal", spacing=dp(8))

                info = Label(
                    text=fa(f"{e.date}   |   {float(e.evap or 0):.1f} میلی‌متر"),
                    font_name=FONT_PATH,
                    color=(0, 0, 0, 1),
                    halign="right",
                )

                btn = Button(
                    text=fa("ویرایش"),
                    font_name=FONT_PATH,
                    size_hint_x=None,
                    width=dp(90),
                    background_normal="",
                    background_color=(0.15, 0.35, 0.75, 1),
                )
                btn.bind(on_release=lambda _btn, eid=e.id: self.load_evap(eid))

                row.add_widget(btn)
                row.add_widget(info)
                self.ids.e_container.add_widget(row)

            if self.selected_id is None:
                self.clear_form()

        except Exception as e:
            print("Evap refresh_list error:", e)
            traceback.print_exc()
            show_popup(fa("خطا"), fa(str(e)))
        finally:
            db.close()

    def load_evap(self, evap_id):
        db = SessionLocal()
        try:
            e = db.query(Evaporation).filter(Evaporation.id == evap_id).first()
            if not e:
                return

            self.selected_id = e.id
            self.ids.e_date.text = e.date
            self.ids.e_val.text = str(e.evap or 0)
            self.ids.e_save.text = App.get_running_app().fa("ذخیره (ویرایش)")
            self.ids.e_delete.disabled = False

        except Exception as e:
            print("Load evap error:", e)
            traceback.print_exc()
            show_popup(fa("خطا"), fa(str(e)))
        finally:
            db.close()

    def save(self):
        try:
            date = safe_date_str(self.ids.e_date.text)
            if not date:
                show_popup(fa("خطا"), fa("تاریخ باید به شکل 1403/01/01 باشد."))
                return

            raw = (self.ids.e_val.text or "").strip()
            if raw == "":
                show_popup(fa("خطا"), fa("مقدار تبخیر را وارد کنید."))
                return

            try:
                val = float(raw)
            except Exception:
                show_popup(fa("خطا"), fa("مقدار تبخیر باید عددی باشد."))
                return

            db = SessionLocal()
            try:
                if self.selected_id is None:
                    existing = db.query(Evaporation).filter(Evaporation.date == date).first()
                    if existing:
                        existing.evap = val
                    else:
                        db.add(Evaporation(date=date, evap=val))
                else:
                    e = db.query(Evaporation).filter(Evaporation.id == self.selected_id).first()
                    if not e:
                        show_popup(fa("خطا"), fa("رکورد پیدا نشد."))
                        return

                    if e.date != date:
                        dup = db.query(Evaporation).filter(Evaporation.date == date).first()
                        if dup:
                            show_popup(fa("خطا"), fa("برای این تاریخ قبلاً تبخیر ثبت شده است."))
                            return

                    e.date = date
                    e.evap = val

                db.commit()
            finally:
                db.close()

            self.refresh_list()
            App.get_running_app().root.get_screen("dash").refresh()
            show_popup(fa("انجام شد"), fa("رکورد تبخیر ذخیره شد."))

        except Exception as e:
            print("Evap save error:", e)
            traceback.print_exc()
            show_popup(fa("خطای برنامه"), fa(str(e)))

    def delete(self):
        try:
            if self.selected_id is None:
                return

            db = SessionLocal()
            try:
                db.query(Evaporation).filter(Evaporation.id == self.selected_id).delete()
                db.commit()
            finally:
                db.close()

            self.clear_form()
            self.refresh_list()
            App.get_running_app().root.get_screen("dash").refresh()
            show_popup(fa("انجام شد"), fa("رکورد تبخیر حذف شد."))

        except Exception as e:
            print("Evap delete error:", e)
            traceback.print_exc()
            show_popup(fa("خطای برنامه"), fa(str(e)))

# -------------------------
# KV (single-file)
# اصلاح مهم: به جای __main__.fa از app.fa استفاده شده
# -------------------------
KV = r'''
#:import dp kivy.metrics.dp

<Label>:
    font_name: "Vazir-Black.ttf"
    text_size: self.size
    halign: "right"
    valign: "middle"

<Button>:
    font_name: "Vazir-Black.ttf"
    background_normal: ""
    background_color: (0.15, 0.35, 0.75, 1)

<TextInput>:
    font_name: "Vazir-Black.ttf"
    multiline: False
    halign: "right"
    padding: [dp(10), dp(12), dp(10), dp(12)]

ScreenManager:
    DashboardScreen:
        name: "dash"
    FarmsScreen:
        name: "farms"
    EvapScreen:
        name: "evap"

<DashboardScreen>:
    BoxLayout:
        orientation: "vertical"
        padding: dp(10)
        spacing: dp(10)

        BoxLayout:
            size_hint_y: None
            height: dp(52)
            canvas.before:
                Color:
                    rgba: (0.10, 0.20, 0.30, 1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(14)]
            Label:
                text: app.fa("سامانه هوشمند آبیاری نیشکر")
                bold: True
                font_size: "18sp"
                color: (1,1,1,1)

        BoxLayout:
            size_hint_y: None
            height: dp(38) if root.banner_text else dp(0)
            opacity: 1 if root.banner_text else 0
            canvas.before:
                Color:
                    rgba: (1.0, 0.85, 0.2, 1) if root.banner_text else (0,0,0,0)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(12)]
            Label:
                text: root.banner_text
                color: (0.15,0.15,0.15,1)
                font_size: "14sp"

        BoxLayout:
            size_hint_y: None
            height: dp(92)
            spacing: dp(10)

            BoxLayout:
                orientation: "vertical"
                padding: dp(10)
                canvas.before:
                    Color:
                        rgba: (1,1,1,1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(14)]
                Label:
                    id: kpi_total
                    text: ""
                    color: (0.25,0.25,0.25,1)
                    font_size: "13sp"
                Label:
                    id: kpi_total_val
                    text: "0"
                    color: (0.05,0.05,0.05,1)
                    font_size: "22sp"
                    bold: True

            BoxLayout:
                orientation: "vertical"
                padding: dp(10)
                canvas.before:
                    Color:
                        rgba: (1,1,1,1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(14)]
                Label:
                    id: kpi_critical
                    text: ""
                    color: (0.25,0.25,0.25,1)
                    font_size: "13sp"
                Label:
                    id: kpi_critical_val
                    text: "0"
                    color: (0.90, 0.15, 0.15, 1)
                    font_size: "22sp"
                    bold: True

            BoxLayout:
                orientation: "vertical"
                padding: dp(10)
                canvas.before:
                    Color:
                        rgba: (1,1,1,1)
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(14)]
                Label:
                    id: kpi_cum
                    text: ""
                    color: (0.25,0.25,0.25,1)
                    font_size: "13sp"
                Label:
                    id: kpi_cum_val
                    text: "0"
                    color: (0.05,0.05,0.05,1)
                    font_size: "18sp"
                    bold: True

        ScrollView:
            do_scroll_x: False
            BoxLayout:
                id: farms_container
                orientation: "vertical"
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(10)

        BoxLayout:
            size_hint_y: None
            height: dp(52)
            spacing: dp(10)

            Button:
                text: app.fa("تبخیر")
                on_release: app.root.current = "evap"

            Button:
                text: app.fa("مزارع")
                on_release: app.root.current = "farms"

            Button:
                text: app.fa("بروزرسانی")
                background_color: (0.12, 0.55, 0.30, 1)
                on_release: root.refresh()

<FarmsScreen>:
    BoxLayout:
        orientation: "vertical"
        padding: dp(10)
        spacing: dp(10)

        BoxLayout:
            size_hint_y: None
            height: dp(52)
            canvas.before:
                Color:
                    rgba: (0.10, 0.20, 0.30, 1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(14)]
            Label:
                text: app.fa("مدیریت مزارع")
                bold: True
                font_size: "18sp"
                color: (1,1,1,1)

        BoxLayout:
            orientation: "vertical"
            size_hint_y: None
            height: dp(240)
            padding: dp(10)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: (1,1,1,1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(14)]

            TextInput:
                id: in_name
                hint_text: app.fa("نام مزرعه")

            TextInput:
                id: in_area
                hint_text: app.fa("مساحت (هکتار)")
                input_filter: "float"

            TextInput:
                id: in_cpe
                hint_text: app.fa("حد مجاز تبخیر / CPE هدف (میلی‌متر)")
                input_filter: "float"

            TextInput:
                id: in_last
                hint_text: app.fa("آخرین آبیاری (مثال: 1403/01/01)")

        BoxLayout:
            size_hint_y: None
            height: dp(52)
            spacing: dp(10)

            Button:
                id: btn_save
                text: app.fa("ذخیره (افزودن)")
                background_color: (0.12, 0.55, 0.30, 1)
                on_release: root.save()

            Button:
                id: btn_reset
                text: app.fa("آبیاری مجدد")
                disabled: True
                background_color: (1.0, 0.60, 0.0, 1)
                on_release: root.restart_irrigation()

            Button:
                id: btn_delete
                text: app.fa("حذف")
                disabled: True
                background_color: (0.90, 0.15, 0.15, 1)
                on_release: root.delete()

        Button:
            text: app.fa("پاک کردن فرم")
            size_hint_y: None
            height: dp(44)
            background_color: (0.35, 0.35, 0.35, 1)
            on_release: root.clear_form()

        Label:
            text: app.fa("لیست مزارع (برای ویرایش، انتخاب کنید)")
            size_hint_y: None
            height: dp(26)
            color: (0.25,0.25,0.25,1)

        ScrollView:
            do_scroll_x: False
            BoxLayout:
                id: list_container
                orientation: "vertical"
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(10)

        BoxLayout:
            size_hint_y: None
            height: dp(52)
            spacing: dp(10)

            Button:
                text: app.fa("داشبورد")
                on_release: app.root.current = "dash"

            Button:
                text: app.fa("تبخیر")
                on_release: app.root.current = "evap"

<EvapScreen>:
    BoxLayout:
        orientation: "vertical"
        padding: dp(10)
        spacing: dp(10)

        BoxLayout:
            size_hint_y: None
            height: dp(52)
            canvas.before:
                Color:
                    rgba: (0.10, 0.20, 0.30, 1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(14)]
            Label:
                text: app.fa("ثبت و مدیریت تبخیر")
                bold: True
                font_size: "18sp"
                color: (1,1,1,1)

        BoxLayout:
            orientation: "vertical"
            size_hint_y: None
            height: dp(190)
            padding: dp(10)
            spacing: dp(8)
            canvas.before:
                Color:
                    rgba: (1,1,1,1)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(14)]

            TextInput:
                id: e_date
                hint_text: app.fa("تاریخ (مثال: 1403/01/01)")

            TextInput:
                id: e_val
                hint_text: app.fa("تبخیر (میلی‌متر)")
                input_filter: "float"

            BoxLayout:
                size_hint_y: None
                height: dp(48)
                spacing: dp(10)

                Button:
                    id: e_save
                    text: app.fa("ذخیره (افزودن/به‌روزرسانی)")
                    background_color: (0.12, 0.55, 0.30, 1)
                    on_release: root.save()

                Button:
                    id: e_delete
                    text: app.fa("حذف")
                    disabled: True
                    background_color: (0.90, 0.15, 0.15, 1)
                    on_release: root.delete()

                Button:
                    text: app.fa("پاک کردن")
                    background_color: (0.35, 0.35, 0.35, 1)
                    on_release: root.clear_form()

        Label:
            text: app.fa("تبخیرهای ثبت شده (برای ویرایش، روی دکمه بزنید)")
            size_hint_y: None
            height: dp(26)
            color: (0.25,0.25,0.25,1)

        ScrollView:
            do_scroll_x: False
            BoxLayout:
                id: e_container
                orientation: "vertical"
                size_hint_y: None
                height: self.minimum_height
                spacing: dp(10)

        BoxLayout:
            size_hint_y: None
            height: dp(52)
            spacing: dp(10)

            Button:
                text: app.fa("داشبورد")
                on_release: app.root.current = "dash"

            Button:
                text: app.fa("مزارع")
                on_release: app.root.current = "farms"
'''

class SmartIrrigationApp(App):
    # این متد برای استفاده در KV است: app.fa("...")
    def fa(self, text):
        return fa(text)

    def build(self):
        if not os.path.exists(os.path.join(APP_DIR, FONT_PATH)) and not os.path.exists(FONT_PATH):
            print("هشدار: Vazir-Black.ttf کنار main.py پیدا نشد.")
        return Builder.load_string(KV)

if __name__ == "__main__":
    SmartIrrigationApp().run()


