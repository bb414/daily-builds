"""Payees, categories and payment methods.

Descriptions are cleaned of the dates, times, card numbers and references
that change every month, reduced to a payee key (the first three meaningful
words), grouped with related keys, sorted into a category and matched to the
way they were paid.
"""

import functools

from .common import cmp, js_regex, js_trim, text_or, truthy

LEAD_WORDS = ['CARD PAYMENT TO', 'CARD PAYMENT', 'CARD PURCHASE', 'DEBIT CARD PAYMENT', 'CONTACTLESS PAYMENT',
              'CONTACTLESS', 'DIRECT DEBIT PAYMENT TO', 'DIRECT DEBIT PAYMENT', 'DIRECT DEBIT TO', 'DIRECT DEBIT',
              'STANDING ORDER TO', 'STANDING ORDER', 'FASTER PAYMENT TO', 'FASTER PAYMENTS', 'FASTER PAYMENT',
              'BILL PAYMENT TO', 'BILL PAYMENT', 'PAYMENT TO', 'RECURRING PAYMENT', 'RECURRING CARD PAYMENT',
              'MOBILE PAYMENT', 'ONLINE PAYMENT', 'PURCHASE', 'POS', 'VIS', 'VISA', 'DEB', 'DD', 'DDR', 'SO', 'STO',
              'FPO', 'FPI', 'BGC', 'BP', 'TFR', 'CPT', 'TO', 'FROM']
TRAIL_WORDS = ['DD', 'DDR', 'SO', 'STO', 'FPO', 'FPI', 'BGC', 'DEB', 'POS', 'VIS', 'GB', 'GBR', 'UK', 'IE', 'IRL', 'LU',
               'LUX', 'NL', 'NLD', 'US', 'USA', 'DE', 'FR', 'LONDON', 'INTERNET', 'ONLINE', 'APPLE PAY', 'GOOGLE PAY',
               'VIA APPLE PAY', 'VIA GOOGLE PAY', 'CONTACTLESS', 'DIRECT DEBIT', 'STANDING ORDER', 'GBP']
PROCESSORS = ['PAYPAL', 'PP', 'SQ', 'SUMUP', 'IZ', 'ZETTLE', 'ZTL', 'STRIPE', 'GOOGLE', 'SP', 'CRV', 'WWW', 'TST',
              'CKO', 'SMP', 'PADDLE', 'FS', 'DNH', 'WL']
GENERIC = ['THE', 'PAYMENT', 'PAYMENTS', 'TRANSFER', 'CARD', 'BANK', 'ONLINE', 'MOBILE', 'DIRECT', 'DEBIT', 'CREDIT',
           'MR', 'MRS', 'MS', 'MISS', 'DR', 'LTD', 'LIMITED', 'PLC', 'AND', 'CO', 'UK']

# Dates, times, card numbers and references that change every month, removed in this order.
_VOLATILE = [js_regex(source) for source in [
    r'\bON \d{1,2}[ \/\-]?[A-Z]{3}(?:[ \/\-]?\d{2,4})?\b',
    r'\b\d{1,2}[\/\-.]\d{1,2}(?:[\/\-.]\d{2,4})?\b',
    r'\b\d{1,2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{0,4}\b',
    r'\b\d{1,2}:\d{2}(?::\d{2})?\b',
    r'[X*]{2,}\d{2,}',
    r'\bCD \d{3,}\b',
    r'\b(GBP|EUR|USD)\s*\d+(?:\.\d+)?\b',
    r'\b\d+\.\d{2}\b',
    r'\b(REF|REFERENCE|MANDATE|MANDATE NO|MANDATE REF|INV|INVOICE|ORDER|TXN|ID)\b[:.#]?\s*\S*',
]]
_DASHES = js_regex(r'[\u2013\u2014]')


def clean_description(desc):
    """Upper-case a description and blank out the parts that change from month to month."""
    t = text_or(desc).upper()
    t = _DASHES.sub(' ', t.replace('\u2019', "'"))
    for pattern in _VOLATILE:
        t = pattern.sub(' ', t)
    return t


_TOKEN_SPLIT = js_regex(r"[^A-Z0-9&+'.\/-]+")
_TOKEN_ENDS = js_regex(r"^[.\/'-]+|[.\/'-]+$")
_ALL_DIGITS = js_regex(r'^\d+$')
_DIGIT = js_regex(r'\d')


def tokens(t):
    """The words of a cleaned description, dropping reference numbers."""
    out = []
    for w in _TOKEN_SPLIT.split(t):
        w = _TOKEN_ENDS.sub('', w)
        if not w:
            continue
        if _ALL_DIGITS.search(w):
            if len(w) <= 2:
                out.append(w)
            continue
        digits = len(_DIGIT.findall(w))
        if digits >= 3 or (digits >= 2 and len(w) >= 5):
            continue
        out.append(w)
    return out


def strip_ends(toks):
    """Remove payment-method words from the start and country or method words from the end."""
    changed = True
    while changed and len(toks) > 1:
        changed = False
        for word in LEAD_WORDS:
            size = len(word.split(' '))
            if len(toks) > size and ' '.join(toks[:size]) == word:
                toks = toks[size:]
                changed = True
                break
        if changed:
            continue
        for word in TRAIL_WORDS:
            size = len(word.split(' '))
            if len(toks) > size and ' '.join(toks[len(toks) - size:]) == word:
                toks = toks[:len(toks) - size]
                changed = True
                break
    return toks


def payee_key(desc):
    """The payee key used to group payments: the first three meaningful words of the description."""
    t = clean_description(desc)
    star = t.find('*')
    if star >= 0:
        left, right = js_trim(t[:star]), js_trim(t[star + 1:])
        left_toks = strip_ends(tokens(left))
        if not left_toks or left_toks[-1] in PROCESSORS:
            t = right or left
        else:
            t = left
    toks = strip_ends(tokens(t))
    if len(toks) > 1 and toks[0] in PROCESSORS and toks[0] != 'GOOGLE':
        toks = toks[1:]
    toks = toks[:3]
    while len(toks) > 1 and toks[-1] in ('&', '-', '+', 'AND'):
        toks.pop()
    key = js_trim(' '.join(toks))
    return key or js_trim(text_or(desc).upper())[:30] or '(NO DESCRIPTION)'


_ONE_CAPITAL = js_regex(r'^[A-Z][a-z]?$')
_CODE_WORD = js_regex(r'^[A-Z0-9&+]+$')


def display_name(key):
    """A payee key as a name for people: 'MOBI-MOTO SIM ONLY' becomes 'Mobi-moto Sim Only', 'TV' stays."""
    words = []
    for w in key.split(' '):
        if len(w) <= 2 and not _ONE_CAPITAL.search(w) and _CODE_WORD.search(w):
            words.append(w)
        else:
            words.append(w[:1] + w[1:].lower())
    return ' '.join(words)


def _key_order(a, b):
    return (len(a.split(' ')) - len(b.split(' '))) or cmp(a, b)


def group_keys(keys):
    """Groups whose key is the first word or words of another key are the same payee.

    Returns {key: parent key}.
    """
    parent = {}
    for k in sorted(keys, key=functools.cmp_to_key(_key_order)):
        toks = k.split(' ')
        parent[k] = k
        for n in range(len(toks) - 1, 0, -1):
            pre = ' '.join(toks[:n])
            if pre not in parent:
                continue
            head = toks[0]
            if n == 1 and (len(head) < 4 or head in GENERIC):
                continue
            parent[k] = parent[pre]
            break
    return parent


def _category(cid, label, essential, words, cost=True):
    return {'id': cid, 'label': label, 'essential': essential, 'cost': cost, 'words': words}


CATEGORIES = [
    _category('savings', 'Savings and moving money between your accounts', False,
              ['SAVINGS', 'SAVER', 'ISA', 'LISA', 'POT', 'POTS', 'INVEST', 'INVESTMENT', 'TO SAVINGS',
               'SAVINGS ACCOUNT', 'MONEYBOX', 'VANGUARD', 'PREMIUM BONDS', 'NS&I', 'OWN ACCOUNT'], cost=False),
    _category('housing', 'Rent and housing', True,
              ['RENT', 'LETTINGS', 'LETTING', 'LANDLORD', 'MORTGAGE', 'HOUSING', 'ACCOMMODATION', 'HALLS', 'RESIDENCE',
               'ESTATES', 'PROPERTY', 'SERVICE CHARGE']),
    _category('council', 'Council tax', True, ['COUNCIL', 'COUNCIL TAX', 'CTAX', 'BOROUGH', 'DISTRICT COUNCIL']),
    _category('energy', 'Energy and water', True,
              ['ENERGY', 'ELECTRIC', 'ELECTRICITY', 'GAS', 'WATER', 'POWER', 'UTILITIES', 'UTILITY', 'OCTOPUS', 'EDF',
               'EON', 'E.ON', 'OVO', 'BRITISH GAS', 'SCOTTISH POWER', 'SO ENERGY', 'HEATING']),
    _category('finance', 'Loans and credit', True,
              ['LOAN', 'LOANS', 'CREDIT CARD', 'KLARNA', 'CLEARPAY', 'LAYBUY', 'PAYPAL CREDIT', 'FINANCE', 'REPAYMENT',
               'HIRE PURCHASE', 'BNPL', 'OVERDRAFT']),
    _category('insurance', 'Insurance and cover', True,
              ['INSURANCE', 'INS', 'INSURE', 'COVER', 'ASSURANCE', 'MUTUAL', 'WARRANTY', 'PROTECT', 'PROTECTION',
               'BREAKDOWN']),
    _category('telecoms', 'Phone and broadband', True,
              ['MOBILE', 'BROADBAND', 'FIBRE', 'SIM', 'TELECOM', 'TELECOMS', 'WIFI', 'INTERNET SERVICE', 'VODAFONE',
               'O2', 'EE', 'GIFFGAFF', 'VIRGIN MEDIA', 'TALKTALK', 'PLUSNET', 'SMARTY', 'LEBARA', 'TESCO MOBILE',
               'VOXI', 'HYPEROPTIC', 'PHONE']),
    _category('tv', 'TV and video', False,
              ['TV', 'STREAM', 'STREAMING', 'VIDEO', 'FILMS', 'CINEMA', 'NETFLIX', 'DISNEY', 'DISNEY PLUS',
               'PRIME VIDEO', 'NOW TV', 'NOWTV', 'PARAMOUNT', 'BRITBOX', 'DAZN', 'YOUTUBE', 'CRUNCHYROLL',
               'APPLE TV', 'TV LICENCE', 'MUBI']),
    _category('music', 'Music and audio', False,
              ['MUSIC', 'SPOTIFY', 'TIDAL', 'DEEZER', 'AUDIBLE', 'SOUNDCLOUD', 'PODCAST', 'AUDIOBOOKS', 'RADIO']),
    _category('software', 'Apps, software and cloud', False,
              ['CLOUD', 'STORAGE', 'ICLOUD', 'DROPBOX', 'ADOBE', 'MICROSOFT', 'MICROSOFT 365', 'OFFICE', 'CANVA',
               'NOTION', 'OPENAI', 'CHATGPT', 'GITHUB', 'GOOGLE ONE', 'GOOGLE STORAGE', 'SOFTWARE', 'HOSTING', 'DOMAIN',
               'DOMAINS', 'VPN', 'PASSWORD', 'ANTIVIRUS', 'APPS', 'APP STORE', 'GRAMMARLY', 'ZOOM', 'SLACK', 'FIGMA']),
    _category('news', 'News and magazines', False,
              ['NEWS', 'NEWSPAPER', 'MAGAZINE', 'MAGAZINES', 'GAZETTE', 'JOURNAL', 'TIMES', 'HERALD', 'ECONOMIST',
               'PRESS', 'LANTERN', 'SUBSTACK', 'PATREON']),
    _category('gym', 'Gym and fitness', False,
              ['GYM', 'FITNESS', 'LEISURE', 'SPORTS CENTRE', 'CLIMBING', 'BOULDERING', 'YOGA', 'PILATES', 'SWIM',
               'SWIMMING', 'STRAVA', 'PELOTON', 'CROSSFIT', 'ATHLETIC']),
    _category('food', 'Food boxes and delivery passes', False,
              ['MEAL', 'MEALS', 'MEAL KIT', 'VEG BOX', 'VEGBOX', 'FOOD BOX', 'HELLOFRESH', 'GOUSTO', 'MINDFUL CHEF',
               'MILK', 'MILKMAN', 'DELIVERY PASS', 'DELIVEROO PLUS', 'UBER ONE', 'COFFEE SUBSCRIPTION']),
    _category('learning', 'Learning and languages', False,
              ['LANGUAGE', 'LANGUAGES', 'LINGO', 'DUOLINGO', 'BABBEL', 'COURSE', 'COURSES', 'TUTOR', 'TUITION',
               'MASTERCLASS', 'COURSERA', 'LEARNING', 'LEARN', 'SCHOOL', 'ACADEMY']),
    _category('gaming', 'Games', False,
              ['GAME', 'GAMES', 'GAMING', 'XBOX', 'PLAYSTATION', 'NINTENDO', 'STEAM', 'CHESS', 'TWITCH']),
    _category('charity', 'Charity and donations', False,
              ['CHARITY', 'CHARITABLE', 'TRUST', 'FOUNDATION', 'DONATION', 'DONATE', 'RNLI', 'OXFAM', 'UNICEF', 'WWF',
               'SHELTER', 'RSPCA', 'NSPCC', 'SAMARITANS', 'APPEAL']),
    _category('transport', 'Transport and travel passes', False,
              ['RAILCARD', 'TRAINLINE', 'BUS PASS', 'TRAVELCARD', 'SEASON TICKET', 'PARKING', 'BIKE', 'CYCLE',
               'SCOOTER', 'CAR CLUB', 'ZIPCAR', 'TRANSPORT', 'RAIL']),
    _category('household', 'Household services', False,
              ['CLEAN', 'CLEANING', 'CLEANER', 'WINDOW', 'GARDEN', 'GARDENING', 'LAUNDRY', 'PEST', 'BINS']),
    _category('personal', 'Personal care', False,
              ['BARBER', 'BARBERS', 'HAIR', 'SALON', 'NAILS', 'BEAUTY', 'DENTAL', 'DENTIST', 'OPTICIAN',
               'CONTACT LENSES', 'PHARMACY']),
    _category('memberships', 'Memberships and clubs', False,
              ['MEMBERSHIP', 'MEMBERS', 'CLUB', 'SOCIETY', 'PRIME', 'PREMIUM', 'SUBSCRIPTION', 'SUBS', 'PLUS']),
    _category('income', 'Income', False, [], cost=False),
    _category('other', 'Other regular payments', False, []),
]
CATEGORY_BY_ID = {c['id']: c for c in CATEGORIES}
DUPLICATE_PRONE = ['tv', 'music', 'software', 'news', 'gym', 'food', 'learning', 'gaming', 'memberships']
BANK_CATEGORY_HINTS = [
    (js_regex(r'saving|transfer|pot', 'i'), 'savings'), (js_regex(r'rent|mortgage|housing', 'i'), 'housing'),
    (js_regex(r'council', 'i'), 'council'), (js_regex(r'utilit|energy|water', 'i'), 'energy'),
    (js_regex(r'insur', 'i'), 'insurance'), (js_regex(r'phone|mobile|broadband|internet', 'i'), 'telecoms'),
    (js_regex(r'entertain|subscri|stream', 'i'), 'tv'), (js_regex(r'fitness|sport|gym', 'i'), 'gym'),
    (js_regex(r'charit|donat|gift', 'i'), 'charity'), (js_regex(r'transport|travel', 'i'), 'transport'),
    (js_regex(r'education|learn', 'i'), 'learning'),
]
_DOTS_AND_SLASHES = js_regex(r'[.\/]')


def category_of(cid):
    """The category record for an id, falling back to 'other'."""
    return CATEGORY_BY_ID.get(cid) or CATEGORY_BY_ID['other']


def categorise(text, bank_category=None):
    """Sort a description into a category by its words, then by the bank's own category.

    Returns {'id', 'word'} plus 'bank' when the bank's category decided it.
    """
    words = ' ' + ' '.join(tokens(_DOTS_AND_SLASHES.sub(' ', clean_description(text)))) + ' '
    for c in CATEGORIES:
        for w in c['words']:
            if ' ' + w + ' ' in words:
                return {'id': c['id'], 'word': w}
    if truthy(bank_category):
        for pattern, cid in BANK_CATEGORY_HINTS:
            if pattern.search(bank_category):
                return {'id': cid, 'word': None, 'bank': bank_category}
    return {'id': 'other', 'word': None}


METHODS = ['direct debit', 'standing order', 'card', 'transfer', 'unknown']
_TYPE_RULES = [
    (js_regex(r'DIRECT DEBIT|\bDDR?\b|\bDD\b'), 'direct debit'),
    (js_regex(r'STANDING ORDER|\bSO\b|\bSTO\b'), 'standing order'),
    (js_regex(r'CARD|\bPOS\b|\bVIS\b|\bDEB\b|CONTACTLESS|PURCHASE|APPLE PAY|GOOGLE PAY'), 'card'),
    (js_regex(r'TRANSFER|\bTFR\b|\bFPO\b|\bFPI\b|FASTER|\bBGC\b|BACS|BANK CREDIT|BILL PAYMENT'), 'transfer'),
]
_DESC_RULES = [
    (js_regex(r'DIRECT DEBIT|^ DDR? |\sDDR?\s*$'), 'direct debit'),
    (js_regex(r'STANDING ORDER|^ SO |^ STO |\sSO\s*$|\sSTO\s*$'), 'standing order'),
    (js_regex(r'CARD PAYMENT|CARD PURCHASE|^ POS |^ VIS |CONTACTLESS|APPLE PAY|GOOGLE PAY'), 'card'),
    (js_regex(r'FASTER PAYMENT|^ FPO |^ FPI |^ BGC |^ TFR |TRANSFER'), 'transfer'),
]


def payment_method(kind, desc):
    """How a payment was made, from the bank's type column or failing that the description."""
    t = (' ' + text_or(kind) + ' ').upper()
    d = (' ' + text_or(desc) + ' ').upper()
    for pattern, method in _TYPE_RULES:
        if pattern.search(t):
            return method
    for pattern, method in _DESC_RULES:
        if pattern.search(d):
            return method
    return 'unknown'
