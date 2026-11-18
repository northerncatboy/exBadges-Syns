from typing import Any, List, Optional, Tuple, Dict, Set
import os
import json
import time
import threading
import requests

from base_plugin import BasePlugin, MethodHook, HookResult, HookStrategy
from hook_utils import find_class
from file_utils import get_cache_dir
from android_utils import run_on_ui_thread
from ui.settings import Header, Input, Text, Divider
from ui.bulletin import BulletinHelper
from ui.alert import AlertDialogBuilder
from client_utils import get_last_fragment

__id__ = "exd_badges_sync"
__name__ = "exDesktop Badges Sync"
__description__ = "@ncatboy4ik | Синхронизирует и отображает значки пользователей и каналов из exDesktop"
__author__ = "northerncatboy"
__version__ = "1.0.0"
__icon__ = "exteraPlugins/1"
__app_version__ = ">=12.10.6"
__sdk_version__ = ">=1.4.5.3"

try:
    from elyx import metainfo as _elyx_meta
    __version__ = _elyx_meta.get("version", __version__)
except Exception:
    pass


def _tr(key: str, default: str = "", **kwargs) -> str:
    try:
        from elyx import strings as elyx_strings
        val = elyx_strings.get(key)
        if val is not None:
            res = str(val)
            if kwargs:
                try:
                    res = res.format(**kwargs)
                except Exception:
                    pass
            return res
    except Exception:
        pass
    if default:
        try:
            return default.format(**kwargs) if kwargs else default
        except Exception:
            return default
    return key


DEFAULT_BADGES_URL = "https://raw.githubusercontent.com/metawka/exDesktop/main/badges.json"
TGK_URL = "https://t.me/ncatboy4ik"
SOURCE_URL = "https://github.com/northerncatboy/exBadges-Syns"

_TLRPC = None


def get_tlrpc():
    global _TLRPC
    if _TLRPC is None:
        try:
            from org.telegram.tgnet import TLRPC
            _TLRPC = TLRPC
        except Exception:
            _TLRPC = find_class("org.telegram.tgnet.TLRPC")
    return _TLRPC


DEFAULT_TYPE_EMOJIS = {
    "developer": 5436088317831588911,
    "bughunter": 5435955706421358710,
    "helper": 5436122668980022844,
    "donor": 5436013804443971578,
    "trusted": 5436179418382906594,
    "default": 5436013804443971578,
}

DEFAULT_BADGE_TITLES = {
    "developer": "Разработчик exDesktop",
    "bughunter": "Охотник за багами",
    "helper": "Помощник проекта exDesktop",
    "donor": "Поддержал разработку",
    "trusted": "Доверенный источник",
    "custom": "Особый значок",
    "default": "Участник проекта exDesktop",
}


class GetUserHook(MethodHook):
    def __init__(self, plugin: "ExdBadgesSyncPlugin"):
        super().__init__()
        self.plugin = plugin

    def after_hooked_method(self, param):
        try:
            user = param.getResult() if param else None
            if user is not None:
                self.plugin.apply_user_badge(user)
        except Exception:
            pass


class PutUserHook(MethodHook):
    def __init__(self, plugin: "ExdBadgesSyncPlugin"):
        super().__init__()
        self.plugin = plugin

    def before_hooked_method(self, param):
        try:
            if param and param.args and len(param.args) > 0:
                user = param.args[0]
                if user is not None:
                    self.plugin.apply_user_badge(user)
        except Exception:
            pass


class GetChatHook(MethodHook):
    def __init__(self, plugin: "ExdBadgesSyncPlugin"):
        super().__init__()
        self.plugin = plugin

    def after_hooked_method(self, param):
        try:
            chat = param.getResult() if param else None
            if chat is not None:
                self.plugin.apply_chat_badge(chat)
        except Exception:
            pass


class PutChatHook(MethodHook):
    def __init__(self, plugin: "ExdBadgesSyncPlugin"):
        super().__init__()
        self.plugin = plugin

    def before_hooked_method(self, param):
        try:
            if param and param.args and len(param.args) > 0:
                chat = param.args[0]
                if chat is not None:
                    self.plugin.apply_chat_badge(chat)
        except Exception:
            pass


class StickersAlertConstructorHook(MethodHook):
    def __init__(self, plugin: "ExdBadgesSyncPlugin"):
        super().__init__()
        self.plugin = plugin

    def after_hooked_method(self, param):
        try:
            if not param:
                return
            alert = param.thisObject
            if alert is None:
                return

            doc_id = self.plugin.find_badge_doc_in_args(param.args, alert)
            if doc_id:
                setattr(alert, "_is_exd_badge", True)
                setattr(alert, "_exd_badge_doc_id", doc_id)
                badge_text = self.plugin.get_badge_bulletin_text(param.args, doc_id)
                setattr(alert, "_exd_badge_text", badge_text)

                def dismiss_later():
                    try:
                        alert.dismiss()
                    except Exception:
                        pass
                    try:
                        fragment = get_last_fragment()
                        BulletinHelper.show_info(badge_text, fragment)
                    except Exception:
                        pass

                run_on_ui_thread(dismiss_later)
        except Exception as e:
            self.plugin.logger.warning(f"Error in StickersAlertConstructorHook: {e}")


class BottomSheetShowHook(MethodHook):
    def __init__(self, plugin: "ExdBadgesSyncPlugin"):
        super().__init__()
        self.plugin = plugin

    def before_hooked_method(self, param):
        try:
            if not param:
                return
            sheet = param.thisObject
            if sheet and getattr(sheet, "_is_exd_badge", False):
                # Отменяем показ стандартного диалога стикеров/эмодзи
                param.setResult(None)
                badge_text = getattr(sheet, "_exd_badge_text", "")
                if badge_text:
                    try:
                        fragment = get_last_fragment()
                        BulletinHelper.show_info(badge_text, fragment)
                    except Exception:
                        pass
        except Exception as e:
            self.plugin.logger.warning(f"Error in BottomSheetShowHook: {e}")


class SetRightDrawableHook(MethodHook):
    def __init__(self, plugin: "ExdBadgesSyncPlugin"):
        super().__init__()
        self.plugin = plugin

    def after_hooked_method(self, param):
        try:
            if not param or not param.args:
                return
            view = param.thisObject
            if view is None:
                return

            drawable = param.args[0]
            if drawable is None:
                setattr(view, "_exd_badge_doc_id", None)
                return

            doc_id = self.plugin._extract_doc_id(drawable)
            if doc_id and doc_id in self.plugin.all_badge_docs:
                setattr(view, "_exd_badge_doc_id", doc_id)
                if hasattr(view, "setRightDrawableOnClick"):
                    try:
                        try:
                            from android_utils import OnClickListener
                        except Exception:
                            class OnClickListener:
                                def __init__(self, fn):
                                    self.fn = fn

                                def onClick(self, v=None):
                                    if callable(self.fn):
                                        return self.fn(v)

                        def on_click(v=None):
                            self.plugin.on_badge_view_clicked(view, doc_id)

                        view.setRightDrawableOnClick(OnClickListener(on_click))
                    except Exception:
                        pass
        except Exception as e:
            self.plugin.logger.warning(f"Error in SetRightDrawableHook: {e}")


class SimpleTextViewTouchHook(MethodHook):
    def __init__(self, plugin: "ExdBadgesSyncPlugin"):
        super().__init__()
        self.plugin = plugin

    def before_hooked_method(self, param):
        try:
            if not param or not param.args:
                return
            view = param.thisObject
            if view is None:
                return

            event = param.args[0]
            if event is None:
                return

            action = event.getAction() & 0xFF
            drawable = getattr(view, "rightDrawable", None)
            if drawable is None and hasattr(view, "getRightDrawable"):
                drawable = view.getRightDrawable()

            if drawable is None:
                return

            doc_id = getattr(view, "_exd_badge_doc_id", None) or self.plugin._extract_doc_id(drawable)

            # Если doc_id не определился из Drawable, проверяем контекст экрана
            if not doc_id:
                fragment = get_last_fragment()
                if fragment:
                    uid = (
                        getattr(fragment, "user_id", None)
                        or getattr(fragment, "userId", None)
                        or getattr(fragment, "dialog_id", None)
                        or getattr(fragment, "dialogId", None)
                    )
                    if uid:
                        try:
                            int_uid = int(uid)
                            if int_uid in self.plugin.users_map:
                                doc_id = self.plugin.users_map[int_uid].get("document_id")
                            elif int_uid in self.plugin.channels_map:
                                doc_id = self.plugin.channels_map[int_uid].get("document_id")
                        except Exception:
                            pass

            if not doc_id or doc_id not in self.plugin.all_badge_docs:
                return

            x = event.getX()
            y = event.getY()

            hit = False
            # 1. Проверка по координатам центра иконки SimpleTextView
            try:
                bx = getattr(view, "rightDrawableX", None)
                by = getattr(view, "rightDrawableY", None)
                if bx is not None and by is not None:
                    if abs(x - float(bx)) <= 70 and abs(y - float(by)) <= 70:
                        hit = True
            except Exception:
                pass

            # 2. Проверка по границам Drawable (Rect bounds)
            if not hit and hasattr(drawable, "getBounds"):
                try:
                    bounds = drawable.getBounds()
                    if bounds:
                        l = getattr(bounds, "left", 0) - 40
                        r = getattr(bounds, "right", 0) + 40
                        t = getattr(bounds, "top", 0) - 40
                        b = getattr(bounds, "bottom", 0) + 40
                        if l <= x <= r and t <= y <= b:
                            hit = True
                except Exception:
                    pass

            # 3. Эвристика: правая часть строки заголовка, где расположен значок
            if not hit and hasattr(view, "getWidth"):
                try:
                    w = float(view.getWidth())
                    if w > 0 and x >= (w - 140):
                        hit = True
                except Exception:
                    pass

            if hit:
                if action == 0:  # ACTION_DOWN
                    setattr(view, "_exd_touch_down", True)
                    if hasattr(view, "getParent") and view.getParent():
                        try:
                            view.getParent().requestDisallowInterceptTouchEvent(True)
                        except Exception:
                            pass
                    param.setResult(True)
                elif action == 1:  # ACTION_UP
                    setattr(view, "_exd_touch_down", False)
                    self.plugin.on_badge_view_clicked(view, doc_id)
                    param.setResult(True)
                elif action == 3:  # ACTION_CANCEL
                    setattr(view, "_exd_touch_down", False)
        except Exception as e:
            self.plugin.logger.warning(f"Error in SimpleTextViewTouchHook: {e}")


class ExdBadgesSyncPlugin(BasePlugin):
    id: str = "exd_badges_sync"

    def __init__(self):
        super().__init__()
        self.id = "exd_badges_sync"
        self.users_map: Dict[int, Dict[str, Any]] = {}
        self.channels_map: Dict[int, Dict[str, Any]] = {}
        self.badged_user_ids: Set[int] = set()
        self.badged_channel_ids: Set[int] = set()
        self.type_emojis: Dict[str, int] = dict(DEFAULT_TYPE_EMOJIS)
        self.all_badge_docs: Set[int] = set(DEFAULT_TYPE_EMOJIS.values())
        self._unhooks: List[Any] = []
        self._stop_event = threading.Event()
        self._sync_thread: Optional[threading.Thread] = None

    def has_settings(self) -> bool:
        return True

    def on_plugin_load(self):
        self.logger.info("Initializing exDesktop Badges Sync...")

        # 1. Загружаем сохраненный сетевой кэш значков (если есть)
        self._load_cached_badges()

        # 2. Регистрируем Xposed-хуки
        self._register_hooks()

        # 3. Регистрируем перехватчик сообщений для команды .badges
        try:
            self.add_on_send_message_hook(priority=0)
        except Exception as e:
            self.logger.warning(f"Error registering send message hook: {e}")

        # 4. ОБЯЗАТЕЛЬНО: При каждом запуске подгружаем свежие значки из сети
        self._stop_event.clear()
        self._sync_thread = threading.Thread(target=self._launch_sync_and_loop, daemon=True)
        self._sync_thread.start()

        # 5. Одноразовое всплывающее окно при первом запуске
        self._check_and_show_welcome()

        self.logger.info("exDesktop Badges Sync loaded successfully.")

    def _check_and_show_welcome(self):
        # Показываем строго 1 раз за все время
        if self.get_setting("welcome_shown", False):
            return

        def show_worker():
            activity = None
            for _ in range(30):
                if self._stop_event.is_set():
                    return
                try:
                    fragment = get_last_fragment()
                    if fragment:
                        activity = fragment.getParentActivity()
                        if activity:
                            break
                except Exception:
                    pass
                time.sleep(0.5)

            # Фиксируем флаг в настройках, чтобы всплывашка больше никогда не показывалась
            self.set_setting("welcome_shown", True)

            def show_dialog():
                try:
                    fragment = get_last_fragment()
                    act = fragment.getParentActivity() if fragment else None
                    if not act:
                        try:
                            from org.telegram.ui import LaunchActivity
                            act = getattr(LaunchActivity, "instance", None)
                        except Exception:
                            pass
                    builder = AlertDialogBuilder(act)
                    builder.set_title("Привет!")

                    def open_link(url: str):
                        try:
                            from org.telegram.messenger.browser import Browser

                            f = get_last_fragment()
                            a = f.getParentActivity() if f else None
                            if not a:
                                try:
                                    from org.telegram.ui import LaunchActivity
                                    a = getattr(LaunchActivity, "instance", None)
                                except Exception:
                                    pass
                            if a:
                                Browser.openUrl(a, url)
                                return
                        except Exception:
                            pass
                        try:
                            from android.content import Intent
                            from android.net import Uri

                            f = get_last_fragment()
                            a = f.getParentActivity() if f else None
                            if not a:
                                try:
                                    from org.telegram.ui import LaunchActivity
                                    a = getattr(LaunchActivity, "instance", None)
                                except Exception:
                                    pass
                            if a:
                                intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                                a.startActivity(intent)
                                return
                        except Exception:
                            pass
                        try:
                            import webbrowser

                            webbrowser.open(url)
                        except Exception:
                            pass

                    def on_tgk_click(bld=None, which=None):
                        open_link(TGK_URL)
                        try:
                            if bld and hasattr(bld, "dismiss"):
                                bld.dismiss()
                        except Exception:
                            pass

                    def on_source_click(bld=None, which=None):
                        open_link(SOURCE_URL)
                        try:
                            if bld and hasattr(bld, "dismiss"):
                                bld.dismiss()
                        except Exception:
                            pass

                    builder.set_positive_button("Мой тгк", on_tgk_click)
                    builder.set_negative_button("Исходный код", on_source_click)
                    builder.show()
                except Exception as e:
                    self.logger.warning(f"Error showing welcome alert: {e}")

            run_on_ui_thread(show_dialog)

        threading.Thread(target=show_worker, daemon=True).start()

    def on_plugin_unload(self):
        self.logger.info("Unloading exDesktop Badges Sync...")
        self._stop_event.set()

        try:
            self.remove_on_send_message_hook()
        except Exception:
            pass

        for unhook in self._unhooks:
            try:
                self.unhook_method(unhook)
            except Exception as e:
                self.logger.warning(f"Error unhooking: {e}")
        self._unhooks.clear()

        self.notify_ui()
        self.logger.info("exDesktop Badges Sync unloaded.")

    def _register_hooks(self):
        try:
            MessagesControllerClass = find_class("org.telegram.messenger.MessagesController")
            if MessagesControllerClass:
                for method_name, hook_inst in (
                    ("getUser", GetUserHook(self)),
                    ("putUser", PutUserHook(self)),
                    ("getChat", GetChatHook(self)),
                    ("putChat", PutChatHook(self)),
                ):
                    try:
                        refs = self.hook_all_methods(MessagesControllerClass, method_name, hook_inst)
                        if refs:
                            if isinstance(refs, list):
                                self._unhooks.extend(refs)
                            else:
                                self._unhooks.append(refs)
                    except Exception as e:
                        self.logger.warning(f"Error hooking MessagesController.{method_name}: {e}")
        except Exception as e:
            self.logger.warning(f"Error finding MessagesController: {e}")

        # Перехват клика по значку (открытие диалога эмодзи/стикеров)
        try:
            StickersAlertClass = find_class("org.telegram.ui.Components.StickersAlert")
            if StickersAlertClass:
                try:
                    refs = self.hook_all_constructors(StickersAlertClass, StickersAlertConstructorHook(self))
                    if refs:
                        if isinstance(refs, list):
                            self._unhooks.extend(refs)
                        else:
                            self._unhooks.append(refs)
                except Exception as e:
                    self.logger.warning(f"Error hooking StickersAlert: {e}")
        except Exception as e:
            self.logger.warning(f"Error finding StickersAlert: {e}")

        try:
            BottomSheetClass = find_class("org.telegram.ui.ActionBar.BottomSheet")
            if BottomSheetClass:
                try:
                    refs = self.hook_all_methods(BottomSheetClass, "show", BottomSheetShowHook(self))
                    if refs:
                        if isinstance(refs, list):
                            self._unhooks.extend(refs)
                        else:
                            self._unhooks.append(refs)
                except Exception as e:
                    self.logger.warning(f"Error hooking BottomSheet.show: {e}")
        except Exception as e:
            self.logger.warning(f"Error finding BottomSheet: {e}")

        # Перехват клика по значку в заголовках и списках (SimpleTextView)
        try:
            SimpleTextViewClass = find_class("org.telegram.ui.ActionBar.SimpleTextView")
            if SimpleTextViewClass:
                for method_name, hook_inst in (
                    ("setRightDrawable", SetRightDrawableHook(self)),
                    ("setRightDrawable2", SetRightDrawableHook(self)),
                    ("onTouchEvent", SimpleTextViewTouchHook(self)),
                ):
                    try:
                        refs = self.hook_all_methods(SimpleTextViewClass, method_name, hook_inst)
                        if refs:
                            if isinstance(refs, list):
                                self._unhooks.extend(refs)
                            else:
                                self._unhooks.append(refs)
                    except Exception as e:
                        self.logger.warning(f"Error hooking SimpleTextView.{method_name}: {e}")
        except Exception as e:
            self.logger.warning(f"Error finding SimpleTextView: {e}")

    def _extract_doc_id(self, obj: Any) -> Optional[int]:
        if obj is None:
            return None
        if isinstance(obj, int):
            return obj if obj in self.all_badge_docs else None

        cached = getattr(obj, "_exd_cached_doc_id", None)
        if cached is not None:
            return cached if cached in self.all_badge_docs else None

        result = None
        for attr in ("documentId", "document_id", "id"):
            val = getattr(obj, attr, None)
            if isinstance(val, int) and val in self.all_badge_docs:
                result = val
                break

        if result is None and hasattr(obj, "getDocumentId"):
            try:
                val = obj.getDocumentId()
                if isinstance(val, int) and val in self.all_badge_docs:
                    result = val
            except Exception:
                pass

        if result is None:
            doc = getattr(obj, "document", None)
            if doc is not None:
                for attr in ("id", "document_id"):
                    val = getattr(doc, attr, None)
                    if isinstance(val, int) and val in self.all_badge_docs:
                        result = val
                        break

        if result is None:
            inner = getattr(obj, "drawable", None)
            if inner is not None and inner is not obj:
                result = self._extract_doc_id(inner)

        try:
            setattr(obj, "_exd_cached_doc_id", result or 0)
        except Exception:
            pass

        return result

    def on_badge_view_clicked(self, view: Any, doc_id: int):
        name = ""
        user_id = 0
        target_peer = None

        # 1. Извлекаем имя из текста самого SimpleTextView
        if view is not None and hasattr(view, "getText"):
            try:
                raw_text = str(view.getText() or "").strip()
                if raw_text and raw_text != "None":
                    name = raw_text
            except Exception:
                pass

        # 2. Проверяем текущий экран (фрагмент)
        fragment = get_last_fragment()
        if fragment is not None:
            try:
                if hasattr(fragment, "getCurrentUser"):
                    target_peer = fragment.getCurrentUser()
                elif hasattr(fragment, "getCurrentChat"):
                    target_peer = fragment.getCurrentChat()
                elif hasattr(fragment, "getUser"):
                    target_peer = fragment.getUser()
                elif hasattr(fragment, "getChat"):
                    target_peer = fragment.getChat()
            except Exception:
                pass

            uid = (
                getattr(fragment, "user_id", None)
                or getattr(fragment, "userId", None)
                or getattr(fragment, "dialog_id", None)
                or getattr(fragment, "dialogId", None)
            )
            if uid:
                try:
                    user_id = int(uid)
                except Exception:
                    pass

        # 3. Извлечение имени пользователя или названия чата из peer
        if not name or name == "None":
            try:
                from org.telegram.messenger import UserObject, MessagesController, UserConfig

                account = getattr(UserConfig, "selectedAccount", 0)
                mc = MessagesController.getInstance(account)
                if target_peer:
                    if hasattr(target_peer, "first_name") or hasattr(target_peer, "last_name"):
                        name = UserObject.getUserName(target_peer)
                    elif hasattr(target_peer, "title"):
                        name = getattr(target_peer, "title", "")
                elif user_id:
                    try:
                        from java.lang import Long
                        uid_arg = Long.valueOf(int(user_id))
                    except Exception:
                        uid_arg = int(user_id)
                    if user_id > 0:
                        u = mc.getUser(uid_arg)
                        if u:
                            name = UserObject.getUserName(u)
                    else:
                        chat_id_val = -int(user_id)
                        try:
                            from java.lang import Long
                            cid_arg = Long.valueOf(chat_id_val)
                        except Exception:
                            cid_arg = chat_id_val
                        c = mc.getChat(cid_arg)
                        if c:
                            name = getattr(c, "title", "")
            except Exception:
                pass

        # 4. Поиск описания значка в базе по user_id или по doc_id
        badge = None
        if user_id:
            badge = self.users_map.get(user_id) or self.channels_map.get(user_id)

        if not badge and doc_id:
            for uid, b in self.users_map.items():
                if b.get("document_id") == doc_id:
                    badge = b
                    if not name or name == "None":
                        try:
                            from org.telegram.messenger import MessagesController, UserConfig, UserObject
                            from java.lang import Long

                            mc = MessagesController.getInstance(UserConfig.selectedAccount)
                            try:
                                u = mc.getUser(Long.valueOf(int(uid)))
                            except Exception:
                                u = mc.getUser(int(uid))
                            if u:
                                name = UserObject.getUserName(u)
                        except Exception:
                            pass
                    break

        if not badge and doc_id:
            for cid, b in self.channels_map.items():
                if b.get("document_id") == doc_id:
                    badge = b
                    if not name or name == "None":
                        try:
                            from org.telegram.messenger import MessagesController, UserConfig
                            from java.lang import Long

                            mc = MessagesController.getInstance(UserConfig.selectedAccount)
                            try:
                                c = mc.getChat(Long.valueOf(int(cid)))
                            except Exception:
                                c = mc.getChat(int(cid))
                            if c:
                                name = getattr(c, "title", "")
                        except Exception:
                            pass
                    break

        if not name or name == "None":
            name = "Пользователь"

        b_type = badge.get("type", "default") if badge else "default"
        custom_text = badge.get("text", "").strip() if badge else ""
        base_title = DEFAULT_BADGE_TITLES.get(
            b_type, DEFAULT_BADGE_TITLES.get("default", "Значок exDesktop")
        )

        if custom_text:
            reason = f"{base_title}: {custom_text}"
        else:
            reason = base_title

        badge_text = f"{name} — {reason}"

        def show():
            try:
                frag = get_last_fragment()
                BulletinHelper.show_info(badge_text, frag)
            except Exception:
                pass

        run_on_ui_thread(show)

    def find_badge_doc_in_args(self, args: Any, alert: Any) -> Optional[int]:
        if not self.all_badge_docs:
            return None
        if args:
            for arg in args:
                doc_id = self._extract_doc_id(arg)
                if doc_id and doc_id in self.all_badge_docs:
                    return doc_id
        if alert:
            for attr in ("selectedDocument", "document", "inputStickerSet", "customEmojiId"):
                val = getattr(alert, attr, None)
                doc_id = self._extract_doc_id(val)
                if doc_id and doc_id in self.all_badge_docs:
                    return doc_id
        return None

    def get_badge_bulletin_text(self, args: Any, doc_id: int) -> str:
        name = ""
        user_id = 0
        target_peer = None

        # 1. Поиск фрагмента и объекта пользователя в аргументах вызова
        if args:
            for arg in args:
                if arg is None:
                    continue
                uid = (
                    getattr(arg, "user_id", None)
                    or getattr(arg, "userId", None)
                    or getattr(arg, "dialog_id", None)
                    or getattr(arg, "dialogId", None)
                )
                if uid:
                    try:
                        user_id = int(uid)
                    except Exception:
                        pass
                if hasattr(arg, "getCurrentUser"):
                    target_peer = arg.getCurrentUser()
                elif hasattr(arg, "getCurrentChat"):
                    target_peer = arg.getCurrentChat()

        # 2. Если не найден в аргументах — проверяем текущий экран (get_last_fragment)
        if not user_id or not target_peer:
            fragment = get_last_fragment()
            if fragment:
                if not user_id:
                    uid = (
                        getattr(fragment, "user_id", None)
                        or getattr(fragment, "userId", None)
                        or getattr(fragment, "dialog_id", None)
                        or getattr(fragment, "dialogId", None)
                    )
                    if uid:
                        try:
                            user_id = int(uid)
                        except Exception:
                            pass
                if not target_peer:
                    if hasattr(fragment, "getCurrentUser"):
                        target_peer = fragment.getCurrentUser()
                    elif hasattr(fragment, "getCurrentChat"):
                        target_peer = fragment.getCurrentChat()

        # 3. Извлечение имени пользователя или названия чата
        try:
            from org.telegram.messenger import UserObject, MessagesController, UserConfig

            account = getattr(UserConfig, "selectedAccount", 0)
            mc = MessagesController.getInstance(account)
            if target_peer:
                if hasattr(target_peer, "first_name") or hasattr(target_peer, "last_name"):
                    name = UserObject.getUserName(target_peer)
                elif hasattr(target_peer, "title"):
                    name = getattr(target_peer, "title", "")
            elif user_id:
                try:
                    from java.lang import Long
                    uid_arg = Long.valueOf(int(user_id))
                except Exception:
                    uid_arg = int(user_id)
                if user_id > 0:
                    u = mc.getUser(uid_arg)
                    if u:
                        name = UserObject.getUserName(u)
                else:
                    chat_id_val = -int(user_id)
                    try:
                        from java.lang import Long
                        cid_arg = Long.valueOf(chat_id_val)
                    except Exception:
                        cid_arg = chat_id_val
                    c = mc.getChat(cid_arg)
                    if c:
                        name = getattr(c, "title", "")
        except Exception:
            pass

        # 4. Поиск описания значка в базе
        badge = None
        if user_id:
            badge = self.users_map.get(user_id) or self.channels_map.get(user_id)

        if not badge:
            for uid, b in self.users_map.items():
                if b.get("document_id") == doc_id:
                    badge = b
                    if not name:
                        try:
                            from org.telegram.messenger import MessagesController, UserConfig, UserObject
                            from java.lang import Long

                            mc = MessagesController.getInstance(UserConfig.selectedAccount)
                            try:
                                u = mc.getUser(Long.valueOf(int(uid)))
                            except Exception:
                                u = mc.getUser(int(uid))
                            if u:
                                name = UserObject.getUserName(u)
                        except Exception:
                            pass
                    break

        if not badge:
            for cid, b in self.channels_map.items():
                if b.get("document_id") == doc_id:
                    badge = b
                    if not name:
                        try:
                            from org.telegram.messenger import MessagesController, UserConfig
                            from java.lang import Long

                            mc = MessagesController.getInstance(UserConfig.selectedAccount)
                            try:
                                c = mc.getChat(Long.valueOf(int(cid)))
                            except Exception:
                                c = mc.getChat(int(cid))
                            if c:
                                name = getattr(c, "title", "")
                        except Exception:
                            pass
                    break

        if not name:
            name = "Пользователь"

        b_type = badge.get("type", "default") if badge else "default"
        custom_text = badge.get("text", "").strip() if badge else ""
        base_title = DEFAULT_BADGE_TITLES.get(
            b_type, DEFAULT_BADGE_TITLES.get("default", "Значок exDesktop")
        )

        if custom_text:
            reason = f"{base_title}: {custom_text}"
        else:
            reason = base_title

        return f"{name} — {reason}"

    def apply_user_badge(self, user: Any):
        if user is None:
            return
        uid = getattr(user, "id", None)
        if uid is None:
            return
        try:
            uid_int = int(uid)
        except Exception:
            return

        # Мгновенная проверка O(1) через Set: если пользователя нет в базе значков, сразу выходим
        if uid_int not in self.badged_user_ids:
            return

        badge = self.users_map.get(uid_int)
        if not badge:
            return

        doc_id = badge.get("document_id")
        if not doc_id:
            return

        # Если значок уже был применен к данному объекту пользователя, пропускаем повторные аллокации
        if getattr(user, "_exd_applied_doc", None) == doc_id:
            return

        tlrpc = get_tlrpc()
        if not tlrpc:
            return

        try:
            current_status = getattr(user, "emoji_status", None)
            if current_status is None or getattr(current_status, "_exd_badge", False):
                status = tlrpc.TL_emojiStatus()
                status.document_id = int(doc_id)
                setattr(status, "_exd_badge", True)
                user.emoji_status = status
                flags = getattr(user, "flags", 0)
                user.flags = int(flags) | 1073741824  # (1 << 30) USER_FLAG_EMOJI_STATUS
                setattr(user, "_exd_applied_doc", doc_id)
        except Exception as e:
            self.logger.warning(f"Failed to apply badge to user {uid_int}: {e}")

    def apply_chat_badge(self, chat: Any):
        if chat is None:
            return
        cid = getattr(chat, "id", None)
        if cid is None:
            return
        try:
            cid_int = int(cid)
        except Exception:
            return

        # Мгновенная проверка O(1) через Set
        if cid_int not in self.badged_channel_ids:
            return

        badge = self.channels_map.get(cid_int)
        if not badge:
            return

        doc_id = badge.get("document_id")
        if not doc_id:
            return

        # Если значок уже применен
        if getattr(chat, "_exd_applied_doc", None) == doc_id:
            return

        tlrpc = get_tlrpc()
        if not tlrpc:
            return

        try:
            current_status = getattr(chat, "emoji_status", None)
            if current_status is None or getattr(current_status, "_exd_badge", False):
                status = tlrpc.TL_emojiStatus()
                status.document_id = int(doc_id)
                setattr(status, "_exd_badge", True)
                chat.emoji_status = status
                setattr(chat, "_exd_applied_doc", doc_id)
        except Exception as e:
            self.logger.warning(f"Failed to apply badge to chat {cid_int}: {e}")

    def reapply_all_active_badges(self):
        # Выполняем обход кэшированных диалогов полностью асинхронно в фоне, не блокируя UI
        def async_worker():
            try:
                from org.telegram.messenger import MessagesController, UserConfig

                max_accounts = getattr(UserConfig, "MAX_ACCOUNT_COUNT", 4)
                for acc in range(max_accounts):
                    cfg = UserConfig.getInstance(acc)
                    if cfg and cfg.isClientActivated():
                        mc = MessagesController.getInstance(acc)
                        users_array = getattr(mc, "users", None)
                        if users_array is not None and hasattr(users_array, "size"):
                            size = users_array.size()
                            for i in range(size):
                                user = users_array.valueAt(i)
                                if user is not None:
                                    self.apply_user_badge(user)

                        chats_array = getattr(mc, "chats", None)
                        if chats_array is not None and hasattr(chats_array, "size"):
                            size = chats_array.size()
                            for i in range(size):
                                chat = chats_array.valueAt(i)
                                if chat is not None:
                                    self.apply_chat_badge(chat)
                self.notify_ui()
            except Exception as e:
                self.logger.warning(f"Error reapplying active badges asynchronously: {e}")

        threading.Thread(target=async_worker, daemon=True).start()

    def notify_ui(self):
        def run():
            try:
                from org.telegram.messenger import NotificationCenter, UserConfig

                max_accounts = getattr(UserConfig, "MAX_ACCOUNT_COUNT", 4)
                for acc in range(max_accounts):
                    cfg = UserConfig.getInstance(acc)
                    if cfg and cfg.isClientActivated():
                        nc = NotificationCenter.getInstance(acc)
                        update_interfaces = getattr(NotificationCenter, "updateInterfaces", 0)
                        main_user_info = getattr(NotificationCenter, "mainUserInfoChanged", 0)
                        if update_interfaces:
                            nc.postNotificationName(update_interfaces, 0xFFFF)
                        if main_user_info:
                            nc.postNotificationName(main_user_info)
            except Exception as e:
                self.logger.warning(f"Error notifying UI: {e}")

        run_on_ui_thread(run)

    def _cache_path(self) -> str:
        try:
            cache_dir = get_cache_dir()
            if cache_dir:
                return os.path.join(cache_dir, "exd_badges.json")
        except Exception:
            pass
        return "/data/data/com.exteragram.messenger/cache/exd_badges.json"

    def _load_cached_badges(self):
        cache_file = self._cache_path()
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._parse_badges(data)
                self.logger.info(
                    f"Loaded cached badges: {len(self.users_map)} users, {len(self.channels_map)} channels."
                )
            except Exception as e:
                self.logger.warning(f"Failed to read cache: {e}")

    def _parse_badges(self, data: Dict[str, Any]):
        types = data.get("types", {})
        type_emojis = dict(DEFAULT_TYPE_EMOJIS)
        for t_name, t_val in types.items():
            if isinstance(t_val, dict) and "emoji" in t_val:
                try:
                    type_emojis[t_name] = int(t_val["emoji"])
                except Exception:
                    pass
        self.type_emojis = type_emojis

        def parse_entries(entries_list: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
            res = {}
            for item in entries_list:
                try:
                    raw_id = item.get("id")
                    if not raw_id:
                        continue
                    item_id = int(raw_id)
                    b_type = item.get("type", "default")
                    doc_id = None
                    if "emoji" in item and item["emoji"]:
                        doc_id = int(item["emoji"])
                    else:
                        doc_id = type_emojis.get(b_type, type_emojis.get("default"))

                    res[item_id] = {
                        "type": b_type,
                        "document_id": doc_id,
                        "text": item.get("text", ""),
                    }
                except Exception:
                    continue
            return res

        users = parse_entries(data.get("users", []))
        channels = parse_entries(data.get("channels", []))
        bots = parse_entries(data.get("bots", []))

        users.update(bots)

        self.users_map = users
        self.channels_map = channels
        self.badged_user_ids = set(users.keys())
        self.badged_channel_ids = set(channels.keys())

        # Собираем список всех ID документов значков для мгновенной фильтрации кликов
        docs = set(type_emojis.values())
        for b in users.values():
            if b.get("document_id"):
                docs.add(int(b["document_id"]))
        for b in channels.values():
            if b.get("document_id"):
                docs.add(int(b["document_id"]))
        self.all_badge_docs = docs

    def sync_badges(self, fresh: bool = True) -> Tuple[bool, str]:
        base_url = DEFAULT_BADGES_URL
        url = f"{base_url}?_t={int(time.time())}" if fresh else base_url

        self.logger.info(f"Syncing badges from {url}...")
        headers = {
            "User-Agent": "exDesktop-Android-Plugin",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                self._parse_badges(data)
                try:
                    with open(self._cache_path(), "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False)
                except Exception as e:
                    self.logger.warning(f"Could not save badges cache: {e}")

                self.reapply_all_active_badges()

                msg = _tr(
                    "sync_success",
                    f"Значки успешно обновлены! Загружено {len(self.users_map)} пользователей "
                    f"и {len(self.channels_map)} каналов.",
                    users=len(self.users_map),
                    channels=len(self.channels_map),
                )
                self.logger.info(msg)
                return True, msg
            else:
                msg = f"Ошибка HTTP {resp.status_code} при загрузке badges.json"
                self.logger.warning(msg)
                return False, msg
        except Exception as e:
            msg = _tr("sync_error", f"Ошибка синхронизации: {e}", error=str(e))
            self.logger.error(msg)
            return False, msg

    def _launch_sync_and_loop(self):
        self.logger.info("Starting fresh background sync on app launch...")

        # 1. Ожидаем готовности экрана, чтобы показать уведомление о начале синхронизации
        for _ in range(25):
            if self._stop_event.is_set():
                return
            try:
                frag = get_last_fragment()
                if frag and frag.getParentActivity():
                    break
            except Exception:
                pass
            time.sleep(0.3)

        def show_start():
            try:
                f = get_last_fragment()
                if f:
                    BulletinHelper.show_info("Синхронизируем значки...", f)
            except Exception:
                pass

        run_on_ui_thread(show_start)

        # 2. Выполняем асинхронную сетевую синхронизацию
        success, _ = self.sync_badges(fresh=True)

        if success:
            def show_end():
                try:
                    f = get_last_fragment()
                    if f:
                        BulletinHelper.show_info("Значки синхронизированы!", f)
                except Exception:
                    pass

            run_on_ui_thread(show_end)

        # 3. Периодический фоновый цикл
        while not self._stop_event.is_set():
            try:
                interval_min = int(self.get_setting("sync_interval", "60"))
            except Exception:
                interval_min = 60
            interval_sec = max(60, interval_min * 60)

            if self._stop_event.wait(timeout=interval_sec):
                break

            self.sync_badges(fresh=True)

    def on_send_message_hook(self, account: int, params: Any) -> HookResult:
        try:
            if not hasattr(params, "message") or not params.message:
                return HookResult()

            text = str(params.message).strip()
            if text == ".badges":
                count_u = len(self.users_map)
                count_c = len(self.channels_map)
                params.message = (
                    f"🏷️ **exDesktop Badges Sync**\n\n"
                    f"• Пользователей со значками: `{count_u}`\n"
                    f"• Каналов со значками: `{count_c}`\n"
                )
                return HookResult(strategy=HookStrategy.MODIFY, params=params)
        except Exception as e:
            self.logger.warning(f"Error in on_send_message_hook: {e}")

        return HookResult()

    def create_settings(self) -> List[Any]:
        def on_sync_click(view=None):
            def run():
                success, msg = self.sync_badges(fresh=True)
                try:
                    fragment = get_last_fragment()
                    if success:
                        BulletinHelper.show_success(msg, fragment)
                    else:
                        BulletinHelper.show_error(msg, fragment)
                except Exception:
                    pass

            threading.Thread(target=run, daemon=True).start()

        sync_cached_subtext = _tr(
            "settings_sync_cached",
            f"Загружено: {len(self.users_map)} пользователей, {len(self.channels_map)} каналов",
            users=len(self.users_map),
            channels=len(self.channels_map),
        )

        return [
            Header(text=_tr("settings_title", "Синхронизация значков exDesktop")),
            Input(
                key="sync_interval",
                text=_tr("settings_interval", "Интервал обновления (в минутах)"),
                subtext=_tr("settings_interval_sub", "Периодичность проверки обновлений в фоне"),
                default="60",
                icon="msg_recent",
            ),
            Divider(),
            Text(
                text=_tr("settings_sync_now", "Синхронизировать сейчас"),
                subtext=sync_cached_subtext,
                icon="msg_retry",
                on_click=on_sync_click,
            ),
        ]
