"""Dashboard wording in English and Hindi.

Spoken-alert copy lives in ``strings.py`` (it doubles as a suppression list); this module
is everything else the screen shows. Keep sentences short and plain: the people Chaukas
protects are often older and frightened. The Hindi needs a native speaker's review before
recording (blueprint 13).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal

from chaukas.ui.strings import ALERTS

Language = Literal["en", "hi"]

_EN_HI: Final[dict[str, tuple[str, str]]] = {
    # Headlines and level titles, one per level
    "headline_quiet": ("You're protected.", "आप सुरक्षित हैं।"),
    "headline_notice": ("Stay alert.", "सतर्क रहें।"),
    "headline_warning": ("Take a moment.", "एक पल रुकें।"),
    "headline_critical": ("Pause before continuing.", "आगे बढ़ने से पहले रुकें।"),
    "headline_critical_recovery": ("Act now to stay safe.", "सुरक्षित रहने के लिए अभी कदम उठाएँ।"),
    "title_quiet": ("Protected", "सुरक्षित"),
    "title_notice": ("Notice", "सूचना"),
    "title_warning": ("Warning", "चेतावनी"),
    "title_critical": ("Critical", "गंभीर"),
    "title_critical_recovery": ("Act now", "अभी कदम उठाएँ"),
    # Status line under the headline
    "status_listening": (
        "Listening to your call and screen. Nothing leaves this PC.",
        "आपकी कॉल और स्क्रीन पर नज़र है। कुछ भी इस पीसी से बाहर नहीं जाता।",
    ),
    "status_paused": ("Paused. Chaukas is not listening.", "रुका हुआ है। चौकस अभी नहीं सुन रहा।"),
    # What the caller seems to want
    "objective_none": ("Nothing suspicious so far", "अब तक कुछ भी संदिग्ध नहीं"),
    "objective_unclear": ("Someone may be pressuring you", "कोई आप पर दबाव डाल रहा हो सकता है"),
    "objective_money_transfer": (
        "Someone on your call may be trying to make you transfer money",
        "कॉल पर कोई आपसे पैसे ट्रांसफर करवाने की कोशिश कर सकता है",
    ),
    "objective_remote_control": (
        "Someone on your call may be trying to take control of your computer",
        "कॉल पर कोई आपके कंप्यूटर का नियंत्रण लेने की कोशिश कर सकता है",
    ),
    "objective_credential_disclosure": (
        "Someone on your call may be trying to get your OTP or password",
        "कॉल पर कोई आपका OTP या पासवर्ड लेने की कोशिश कर सकता है",
    ),
    # Why-panel sentences, one per evidence label
    "reason_authority": ("Caller claimed to be an official", "कॉलर ने खुद को अधिकारी बताया"),
    "reason_threat": ("Caller threatened you", "कॉलर ने आपको धमकाया"),
    "reason_urgency": ("Caller rushed you", "कॉलर ने जल्दी करने का दबाव डाला"),
    "reason_isolation": ("Caller told you to keep it secret", "कॉलर ने बात छिपाने को कहा"),
    "reason_surveillance": ("Caller told you to stay on the call", "कॉलर ने कॉल पर बने रहने को कहा"),
    "reason_money_request": ("Caller asked you to send money", "कॉलर ने पैसे भेजने को कहा"),
    "reason_remote_access_request": (
        "Caller asked you to install an app or share your screen",
        "कॉलर ने ऐप इंस्टॉल करने या स्क्रीन शेयर करने को कहा",
    ),
    "reason_credential_request": (
        "Caller asked for your OTP or password",
        "कॉलर ने आपका OTP या पासवर्ड माँगा",
    ),
    "reason_user_digits_spoken": ("You read out a code", "आपने एक कोड बोला"),
    "reason_bank_page": ("A banking page is open", "बैंकिंग पेज खुला है"),
    "reason_transfer_page": ("A money-transfer page is open", "पैसे ट्रांसफर का पेज खुला है"),
    "reason_download_executable": ("A program was downloaded", "एक प्रोग्राम डाउनलोड हुआ"),
    "reason_remote_app_started": ("A remote-access app started", "रिमोट-एक्सेस ऐप चालू हुआ"),
    "reason_otp_field_visible": ("A page is asking for an OTP", "एक पेज OTP माँग रहा है"),
    "reason_password_field_visible": ("A page is asking for a password", "एक पेज पासवर्ड माँग रहा है"),
    # Short labels for evidence chips
    "kind_authority": ("Authority", "अधिकार"),
    "kind_threat": ("Threat", "धमकी"),
    "kind_urgency": ("Urgency", "जल्दबाज़ी"),
    "kind_isolation": ("Isolation", "छिपाव"),
    "kind_surveillance": ("Surveillance", "निगरानी"),
    "kind_money_request": ("Money ask", "पैसे की माँग"),
    "kind_remote_access_request": ("Remote access", "रिमोट एक्सेस"),
    "kind_credential_request": ("OTP ask", "OTP की माँग"),
    "kind_user_digits_spoken": ("Code spoken", "कोड बोला"),
    # Attack patterns and their steps
    "chain_none": ("No pattern yet", "अभी कोई पैटर्न नहीं"),
    "chain_digital_arrest": ("Digital arrest", "डिजिटल अरेस्ट"),
    "chain_remote_access": ("Remote access", "रिमोट एक्सेस"),
    "chain_credential_theft": ("Credential theft", "OTP/पासवर्ड चोरी"),
    "step_authority": ("Authority", "अधिकार"),
    "step_threat": ("Threat", "धमकी"),
    "step_control": ("Isolation", "छिपाव"),
    "step_money": ("Money", "पैसे"),
    "step_bank_ctx": ("Bank page", "बैंक पेज"),
    "step_fear": ("Fear", "डर"),
    "step_install_req": ("Install", "इंस्टॉल"),
    "step_remote_ctx": ("Remote app", "रिमोट ऐप"),
    "step_urgency": ("Urgency", "जल्दबाज़ी"),
    "step_cred_req": ("OTP ask", "OTP माँग"),
    "step_cred_ctx": ("OTP page", "OTP पेज"),
    "steps_of": ("{seen} of {total} steps", "{total} में से {seen} चरण"),
    # Navigation and section labels
    "nav_home": ("Home", "होम"),
    "nav_why": ("Why", "क्यों"),
    "nav_privacy": ("Privacy", "गोपनीयता"),
    "nav_settings": ("Settings", "सेटिंग्स"),
    "risk_now": ("Risk right now", "अभी का जोखिम"),
    "live_call": ("Live call", "लाइव कॉल"),
    "this_call": ("This call", "यह कॉल"),
    "pressure": ("Pressure", "दबाव"),
    "risk": ("Risk", "जोखिम"),
    "risk_over_time": ("Risk over time", "समय के साथ जोखिम"),
    "peak": ("Peak", "अधिकतम"),
    "attack_pattern": ("Attack pattern", "हमले का पैटर्न"),
    "range_1m": ("1 min", "1 मिनट"),
    "range_5m": ("5 min", "5 मिनट"),
    "range_all": ("Whole call", "पूरी कॉल"),
    # Actions
    "action_pause": ("Pause", "रोकें"),
    "action_resume": ("Resume", "फिर शुरू"),
    "action_end": ("End session", "सत्र खत्म"),
    "action_contact": ("Contact", "भरोसेमंद"),
    "action_helpline": ("Helpline", "हेल्पलाइन"),
    "action_privacy": ("Privacy", "गोपनीयता"),
    "type_label": ("Try it: type a line", "आज़माएँ: एक पंक्ति लिखें"),
    "type_hint": ("Type what the caller said…", "कॉलर ने जो कहा वह लिखें…"),
    "send": ("Send", "भेजें"),
    "speaker_caller": ("Caller", "कॉलर"),
    "speaker_user": ("You", "आप"),
    "waiting": (
        "Waiting for a call. Chaukas starts when call audio plays.",
        "कॉल का इंतज़ार है। कॉल की आवाज़ आते ही चौकस शुरू हो जाता है।",
    ),
    "no_evidence": ("No warning signs yet", "अभी कोई चेतावनी संकेत नहीं"),
    # Why page and alert cards
    "why_title": ("Why Chaukas is warning you", "चौकस आपको क्यों चेतावनी दे रहा है"),
    "why_empty": (
        "Nothing to explain yet. When Chaukas warns you, every reason appears here with the "
        "moment it happened.",
        "अभी बताने को कुछ नहीं। चेतावनी मिलने पर हर कारण यहाँ समय के साथ दिखेगा।",
    ),
    "verify_btn": ("Verify independently", "खुद जाँच करें"),
    "verify_detail": (
        "Hang up. Contact the organisation using a number you find yourself (on your card, "
        "passbook, or official website), not one the caller gave you.",
        "कॉल काटें। संस्था से उस नंबर पर संपर्क करें जो आपने खुद ढूँढा हो (कार्ड, पासबुक "
        "या आधिकारिक वेबसाइट पर), कॉलर का दिया नंबर नहीं।",
    ),
    "contact_btn": ("Show trusted contact", "भरोसेमंद संपर्क दिखाएँ"),
    "contact_call": ("Call from your phone", "अपने फ़ोन से कॉल करें"),
    "contact_missing": (
        "No trusted contact yet. Add one in Settings.",
        "अभी कोई भरोसेमंद संपर्क नहीं। सेटिंग्स में जोड़ें।",
    ),
    "helpline_btn": ("Cybercrime helpline 1930", "साइबर क्राइम हेल्पलाइन 1930"),
    "helpline_detail": (
        "Call 1930 or report at cybercrime.gov.in",
        "1930 पर कॉल करें या cybercrime.gov.in पर शिकायत करें",
    ),
    "understand": ("I understand this warning", "मैं यह चेतावनी समझता/समझती हूँ"),
    "continue": ("Continue anyway", "फिर भी जारी रखें"),
    "dismiss": ("Dismiss", "बंद करें"),
    "why_btn": ("Why?", "क्यों?"),
    "open_chaukas": ("Open Chaukas", "चौकस खोलें"),
    "wiped": ("Temporary conversation data discarded.", "अस्थायी बातचीत का डेटा हटा दिया गया।"),
    # Privacy page
    "privacy_title": ("Private by design", "डिज़ाइन से ही निजी"),
    "privacy_audio": ("Audio", "आवाज़"),
    "privacy_screen": ("Screen", "स्क्रीन"),
    "privacy_ai": ("AI reasoning", "AI विश्लेषण"),
    "privacy_cloud": ("Cloud upload", "क्लाउड अपलोड"),
    "privacy_local": ("Processed on this PC", "इसी पीसी पर"),
    "privacy_none": ("None", "कोई नहीं"),
    "privacy_note": (
        "Transcripts are kept in memory for 5 minutes and never saved. Ending a session "
        "discards everything Chaukas heard.",
        "बातचीत सिर्फ़ 5 मिनट मेमोरी में रहती है और कभी सेव नहीं होती। सत्र खत्म करने पर "
        "चौकस ने जो सुना सब हटा दिया जाता है।",
    ),
    "end_hint": (
        "Discard everything Chaukas heard in this call.",
        "इस कॉल में चौकस ने जो सुना, सब हटा दें।",
    ),
    "listening": ("Listening", "सुन रहा है"),
    "paused": ("Paused", "रुका हुआ"),
    # Settings page
    "settings_language": ("Language", "भाषा"),
    "settings_contact": ("Trusted contact", "भरोसेमंद संपर्क"),
    "settings_contact_hint": (
        "Someone you trust, shown large when Chaukas warns you. Saved only on this PC.",
        "कोई भरोसेमंद व्यक्ति, जो चेतावनी के समय बड़े अक्षरों में दिखेगा। सिर्फ़ इसी पीसी पर सेव।",
    ),
    "settings_name": ("Name", "नाम"),
    "settings_number": ("Phone number", "फ़ोन नंबर"),
    "settings_save": ("Save", "सेव करें"),
    "settings_saved": ("Saved", "सेव हो गया"),
    "settings_capture": ("Hide alerts from screen sharing", "स्क्रीन शेयर में चेतावनी छिपाएँ"),
    "settings_capture_hint": (
        "Stops a remote caller seeing Chaukas's warnings. Also hides them from screen "
        "recorders on this PC.",
        "रिमोट कॉलर को चौकस की चेतावनी दिखने से रोकता है। इस पीसी के स्क्रीन रिकॉर्डर से भी छिपाता है।",
    ),
}  # fmt: skip

_FROM_ALERTS: Final = {
    "fact_money": "authority_fact",
    "fact_credential": "otp_pre",
    "fact_recovery": "otp_recovery",
    "fact_remote": "remote",
    "ignore_warning": "ignore_warning",
    "verify": "verify",
}

TEXT: Final[Mapping[str, Mapping[Language, str]]] = MappingProxyType(
    {
        **{key: MappingProxyType({"en": en, "hi": hi}) for key, (en, hi) in _EN_HI.items()},
        **{
            key: MappingProxyType({"en": ALERTS[alert].en, "hi": ALERTS[alert].hi})
            for key, alert in _FROM_ALERTS.items()
        },
    }
)


def text(key: str, language: Language, fallback: str | None = None) -> str:
    """The copy for ``key``, or ``fallback`` (default: the key itself) if there is none."""
    entry = TEXT.get(key)
    if entry is None:
        return key if fallback is None else fallback
    return entry[language]


def labels(language: Language) -> dict[str, str]:
    """Every key in one language, for the QML side."""
    return {key: entry[language] for key, entry in TEXT.items()}
