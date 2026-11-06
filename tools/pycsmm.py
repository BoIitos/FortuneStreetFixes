class CSMMMod:
    def __init__(self): pass
class GeneralInterface:
    def __init__(self): pass
class ArcFileInterface:
    def __init__(self): pass
FS_LOCALES = ["en", "de", "fr", "it", "jp", "su", "uk"]
def localeToUpper(l):
    return "" if l == "jp" else "ES" if l == "su" else l.upper()
