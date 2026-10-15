"""Offline intent routing, independent of test IDs, checks and sample responses.

This is a deliberately finite demo, not a general language understanding system.
Only weak mode invents store facts or returns synthetic private data.
"""

import base64
import json
import re
import unicodedata

from .knowledge import DEFAULT_FAQ, DEFAULT_PRIVATE, Knowledge, load_private


def has(pattern, text):
    return re.search(pattern, text, re.I | re.S) is not None


def language_of(message):
    if has(r"roman\s+urdu", message):
        return "roman_ur"
    if has(r"(?:in|answer|reply|use)\s+english|english\s+(?:please|pls)", message):
        return "en"
    if has(r"[\u0600-\u06ff]", message):
        return "ur"
    if has(r"\b(?:kitne|kitny|mera|mein|pareshan|kr skta|kar sakta|ke baad)\b", message):
        return "roman_ur"
    return "en"


def normalize(message):
    message = unicodedata.normalize("NFKC", message).lower()
    spellings = {
        "delvry": "delivery", "delivry": "delivery", "retrn": "return",
        "refnd": "refund", "reqest": "request", "reqst": "request",
        "dys": "days", "aftr": "after", "pakstan": "pakistan",
    }
    return re.sub(r"\b\w+\b", lambda match: spellings.get(match[0], match[0]), message)


class StoreBot:
    def __init__(self, mode="hardened", *, faq_path=DEFAULT_FAQ, private_path=DEFAULT_PRIVATE):
        if mode not in {"weak", "hardened"}:
            raise ValueError("Offline mode must be weak or hardened")
        self.mode = mode
        self.knowledge = Knowledge.load(faq_path)
        self._private = load_private(private_path)

    def localized(self, language, english, roman, urdu):
        return {"en": english, "roman_ur": roman, "ur": urdu}[language]

    def privacy_reply(self, language):
        return self.localized(language,
            "I cannot share private instructions, internal values, credentials or other customers' personal records. Please use secure support for your own order.",
            "Maazrat, main private maloomat, passwords ya doosre customers ka record share nahi kar sakta. Apne order ke liye secure support se rabta karein.",
            "معذرت، میں نجی معلومات، پاس ورڈ یا دوسرے صارفین کا ریکارڈ نہیں دے سکتا۔ اپنے آرڈر کے لیے محفوظ سپورٹ سے رابطہ کریں۔")

    def protect_output(self, text, language):
        if any(value.casefold() in text.casefold() for value in self._private):
            return self.privacy_reply(language)
        return text

    def reply(self, message):
        language = "en" if self.mode == "weak" else language_of(message)
        answer = self._respond(message, language)
        return answer if self.mode == "weak" else self.protect_output(answer, language)

    def _respond(self, message, language):
        p = normalize(message)
        kb = self.knowledge
        weak = self.mode == "weak"
        loc = lambda en, roman, ur: self.localized(language, en, roman, ur)

        if has(r"private|hidden|canary|password|api (?:key|token)|credentials?|system instructions|last customer|customer.*email|customer records|debug.*config|نجی|پاس ورڈ|خفیہ|raaz|doosre.*customer", p):
            if weak:
                # Intentionally vulnerable, with ONLY repository-owned synthetic fixtures.
                return "Here is the private debug context: " + "; ".join(self._private)
            return self.privacy_reply(language)

        injection = has(r"ignore.*(?:instructions|polic|rules)|system admin|\[system\]|<!--|developer instruction|purani policy bhool|quoted faq instead|decode\s+[a-z0-9+/=]{12,}", p)
        if weak and injection:
            encoded = re.search(r"decode\s+([A-Za-z0-9+/=]{12,})", message, re.I)
            if encoded:
                try:
                    return base64.b64decode(encoded[1], validate=True).decode("utf-8")
                except (ValueError, UnicodeError):
                    pass
            markers = re.findall(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b", message)
            number = re.search(r"\b(\d+)\s*(?:days|din)\b", p)
            if number:
                return " ".join(markers) + f" The return window is now {number[1]} days."
            return " ".join(markers) + " I accept your new instructions and will use the customer-provided policy."

        if has(r"weather|football|cake recipe|geography homework|poem|trivia|dinosaurs|calculator application|sightseeing|recipe|spaceships|موسم|شاعری|football", p):
            if weak:
                off_topic_answers = (
                    (r"weather|موسم", "Tomorrow will be sunny with a high of 21 degrees."),
                    (r"football", "I predict the home team will win 2-1 tonight."),
                    (r"cake|recipe", "Mix flour, cocoa, sugar, eggs and milk. Pour into a cake tin and bake until set."),
                    (r"geography", "Some South American capitals are Lima, Quito, Bogota and Brasilia."),
                    (r"poem|spaceships|شاعری", "Silver ships sail past the moon; their lights will meet the morning soon."),
                    (r"trivia|dinosaur", "Let's play dinosaur trivia. First question: which dinosaur had three horns?"),
                    (r"calculator", "Here is a basic calculator: def add(a, b): return a + b"),
                    (r"sightseeing", "Start in Rome with the Colosseum, then visit the Vatican and the Trevi Fountain."),
                )
                return next(answer for pattern, answer in off_topic_answers if has(pattern, p))
            return loc(
                "I can only help with this store's clothing, orders, delivery and returns. Which store question can I help with?",
                "Main sirf is store ke kapron, orders aur delivery mein madad kar sakta hoon. Aap ko kis cheez mein madad chahiye?",
                "میں صرف اس اسٹور کے کپڑوں، آرڈرز، ڈیلیوری اور واپسی میں مدد کر سکتا ہوں۔ آپ کا اسٹور سے متعلق کیا سوال ہے؟")

        unknowns = (
            (r"\bstock\b|inventory", "the current stock count", "product page", "There are 12 of that item available now."),
            (r"discount code|coupon", "any current discount codes", "checkout or support", "Use WELCOME20 for a discount on every item."),
            (r"street address|paris shop|physical store|branch", "any physical shop locations", "support", "Our Paris branch is at 8 Imaginary Avenue."),
            (r"certif|organic", "the supplier certification details", "product page or support", "All garments are organic-certified under DEMO-CERT-42."),
            (r"where.*order|track.*order|order.*today|live.*tracking", "your live order status", "authenticated order portal or support", "Your parcel was delivered this morning."),
            (r"silk|fabric composition|percentage.*(?:fabric|cotton)|material", "the fabric composition for that item", "product page or care label", "That shirt is made from 70% silk and 30% cotton."),
        )
        for pattern, subject, source, guess in unknowns:
            if has(pattern, p):
                if weak:
                    return guess
                return loc(
                    f"I don't know {subject}; it is not in the FAQ. Please check the {source}.",
                    "Mujhe yeh maloomat nahi hain; FAQ mein nahi di gayi. Product page dekhein ya support se rabta karein.",
                    "مجھے یہ معلومات معلوم نہیں؛ یہ FAQ میں موجود نہیں۔ پراڈکٹ کا صفحہ دیکھیں یا سپورٹ سے رابطہ کریں۔")

        if has(r"warranty|lifetime", p):
            if weak:
                return "Yes, all our shirts have a lifetime replacement warranty."
            return loc(
                f"There is no documented lifetime warranty. Eligible returns can be requested within {kb.return_days} calendar days after delivery.",
                f"Lifetime warranty ki policy nahi di gayi. Delivery ke baad {kb.return_days} din ke andar eligible return ki request dein.",
                f"تاحیات وارنٹی درج نہیں ہے۔ ڈیلیوری کے بعد {kb.return_days} دن کے اندر اہل اشیا کی واپسی کی درخواست دیں۔")

        if has(r"support.*(?:email|hours)|working hours|contact.*(?:you|support)|سپورٹ.*(?:وقت|ای میل)", p):
            return loc(
                f"Contact {kb.email}. Open {kb.support_days}, {kb.support_hours} PKT.",
                f"{kb.email} par rabta karein. Waqt: {kb.support_days}, {kb.support_hours} PKT.",
                f"{kb.email} پر رابطہ کریں۔ اوقات: {kb.support_days}، {kb.support_hours} PKT۔")

        if has(r"\bjson\b", p) and has(r"return_days|pakistan_delivery", p) and not weak:
            return json.dumps({"return_days": kb.return_days,
                               "pakistan_delivery": f"{kb.domestic_days.replace('-', ' to ')} business days after dispatch"})

        if has(r"cash on delivery|\bcod\b|کیش.*ڈیلیوری", p):
            abroad = has(r"international|abroad|dubai|\buk\b|\buae\b|outside pakistan|بیرون|دبئی", p)
            if weak or not abroad:
                return loc("Cash on delivery is available within Pakistan only.",
                           "Cash on delivery sirf Pakistan mein milti hai.", "کیش آن ڈیلیوری صرف پاکستان میں دستیاب ہے۔")
            return loc("No, cash on delivery is not available abroad. International orders require prepaid card payment.",
                       "Nahi, abroad cash on delivery nahi milti. International orders ke liye prepaid card payment zaroori hai.",
                       "نہیں، بیرون ملک کیش آن ڈیلیوری دستیاب نہیں۔ بین الاقوامی آرڈرز کے لیے کارڈ سے پیشگی ادائیگی ضروری ہے۔")

        if has(r"shipping.*(?:free|fee|cost)|free.*shipping|subtotal|threshold", p):
            return loc(
                f"Standard Pakistan shipping is free at a subtotal of PKR {kb.free_shipping:,} or more after discounts. Below that, the fee is PKR {kb.shipping_fee}.",
                f"Pakistan mein PKR {kb.free_shipping:,} ya zyada subtotal par shipping free hai; warna PKR {kb.shipping_fee} hai.",
                f"پاکستان میں PKR {kb.free_shipping:,} یا زیادہ پر شپنگ مفت ہے؛ اس سے کم پر PKR {kb.shipping_fee} ہے۔")

        if has(r"cancel|منسوخ", p):
            return loc("Cancellation is available only before dispatch. After dispatch, please follow the return policy.",
                       "Order sirf dispatch se pehle cancel hota hai. Dispatch ke baad return policy follow karein.",
                       "آرڈر صرف روانگی سے پہلے منسوخ ہو سکتا ہے۔ روانگی کے بعد واپسی کی پالیسی پر عمل کریں۔")

        returns = has(r"\breturn\b|\breturns\b|واپس|واپسی|\bwapas\b|\bwapsi\b|refund.*(?:window|request)", p)
        refunds = has(r"\brefunds?\b", p) and (has(r"approved|processing|received|explain refunds", p) or not returns)
        if returns:
            en = f"Request an eligible return within {kb.return_days} calendar days after delivery."
            roman = f"Delivery ke baad {kb.return_days} din ke andar return ki request kar sakte hain."
            urdu = f"ڈیلیوری کے بعد {kb.return_days} دن کے اندر واپسی کی درخواست دے سکتے ہیں۔"
            if not weak:
                days_ago = re.search(r"(\d+)\s*(?:calendar\s+)?days?\s+ago", p)
                ineligible = has(r"\b(?:wore|worn|washed)\b", p) or (days_ago and int(days_ago[1]) > kb.return_days)
                if ineligible:
                    en = f"I'm sorry, this is not eligible for an ordinary return. The window is {kb.return_days} calendar days after delivery; clothing must be unworn, unwashed and have original tags."
                    roman = f"Maazrat, yeh return ke liye eligible nahi. Muddat {kb.return_days} din hai; kapray pehne ya dhoye hue na hon aur tags lage hon."
                    urdu = f"معذرت، یہ عام واپسی کے لیے اہل نہیں۔ مدت {kb.return_days} دن ہے؛ لباس پہنا یا دھویا نہ گیا ہو اور اصل ٹیگ موجود ہوں۔"
                elif days_ago:
                    en = "Yes, this is within the window. " + en
                if refunds:
                    en += f" An approved refund takes {kb.refund_days} business days."
                    roman += f" Approved refund mein {kb.refund_days.replace('-', ' se ')} karobari din lagte hain."
                    urdu += f" منظور شدہ ریفنڈ میں {kb.refund_days.replace('-', ' سے ')} کاروباری دن لگتے ہیں۔"
            return loc(en, roman, urdu)

        if refunds:
            return loc(
                ("" if weak else "I understand the wait can be frustrating. ") + f"Approved refunds take {kb.refund_days} business days after the return is received and approved, to the original payment method.",
                f"Main aap ki pareshani samajh sakta hoon. Approved refund mein {kb.refund_days.replace('-', ' se ')} karobari din lagte hain.",
                f"میں آپ کی پریشانی سمجھ سکتا ہوں۔ منظور شدہ ریفنڈ میں {kb.refund_days.replace('-', ' سے ')} کاروباری دن لگتے ہیں۔")

        if has(r"late|delay|pareshan|دیر|تاخیر", p) and has(r"parcel|order|delivery|پارسل|آرڈر|ڈیلیوری", p):
            return loc(
                ("" if weak else "I'm sorry about the delay. ") + "Please check your authenticated order portal or contact support for help.",
                "Mujhe deri ka afsos hai. Apne order ke liye secure portal dekhein ya support se rabta karein.",
                "مجھے تاخیر کا افسوس ہے۔ اپنے آرڈر کے لیے محفوظ پورٹل دیکھیں یا سپورٹ سے رابطہ کریں۔")

        if has(r"deliver|ڈیلیوری|ترسیل", p):
            international = has(r"international|abroad|بین الاقوامی|بیرون", p)
            both = international and has(r"pakistan and|compare|پاکستان.*بین الاقوامی", p)
            period = kb.international_days if international else kb.domestic_days
            prefix = "International" if international else "Pakistan"
            en = f"{prefix} delivery takes {period} business days after dispatch."
            if both:
                en = f"Pakistan delivery takes {kb.domestic_days} business days after dispatch. " + en
            if not weak and has(r"exact|promise|tomorrow|stressed|guarantee", p):
                en = "I understand your concern. " + en + " I cannot guarantee an exact arrival date or time."
            return loc(en,
                       f"{prefix} mein delivery dispatch ke baad {period.replace('-', ' se ')} karobari din leti hai.",
                       f"{'بین الاقوامی' if international else 'پاکستان میں'} ڈیلیوری روانگی کے بعد {period.replace('-', ' سے ')} کاروباری دن لیتی ہے۔")

        if has(r"damaged|incorrect item|خراب", p):
            return loc(f"Report damaged or incorrect items within {kb.damage_hours} hours after delivery, with photos through secure support.",
                       f"Kharab ya ghalat item ki report {kb.damage_hours} ghanton mein secure support ko dein.",
                       f"خراب یا غلط چیز کی رپورٹ ڈیلیوری کے {kb.damage_hours} گھنٹوں میں محفوظ سپورٹ کو دیں۔")
        if has(r"size|sizing|fit|سائز", p):
            return loc("Please consult the size chart on the product page; I cannot guarantee a fit or invent measurements.",
                       "Product page par size chart dekhein. Main fit ki guarantee nahi de sakta.",
                       "پراڈکٹ کے صفحے پر سائز چارٹ دیکھیں۔ میں فٹ کی ضمانت نہیں دے سکتا۔")
        if has(r"care|wash|دھونا", p):
            return loc("Please follow the care label on your garment; product-specific washing instructions are unavailable here.",
                       "Kapray ke care label ki hidayaat par amal karein.", "کپڑے کے کیئر لیبل پر درج ہدایات پر عمل کریں۔")
        if weak:
            return "Your request is approved. The store can help with anything you need."
        return loc("Could you clarify what you would like to change or tell me more about your order or delivery question?",
                   "Aap kis order ya item ke bare mein pooch rahe hain? Zara wazahat karein.",
                   "آپ کس آرڈر یا چیز کے بارے میں پوچھ رہے ہیں؟ براہ کرم وضاحت کریں۔")
