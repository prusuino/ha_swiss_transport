"""Generate frontend/line-colors.json from Traewelling/line-colors (CH)."""
import csv
import io
import json
import urllib.request

CSV_URL = "https://raw.githubusercontent.com/Traewelling/line-colors/main/line-colors-CH.csv"
OUT = "custom_components/swiss_transport/frontend/line-colors.json"


def is_train(short_name, line):
    if short_name.startswith("s-bahn") or short_name.startswith("schweiz-fernverkehr") or short_name.startswith("rhb"):
        return True
    if short_name == "ostwind-ab" and line.startswith("S"):
        return True
    if short_name == "transn" and line.startswith("R"):
        return True
    return False


NETS = {
    "liemobil", "mobiju-pag", "ostwind-ab", "ostwind-vbsh", "tnw-aagl",
    "tnw-blt", "tnw-bvb", "tnw-pag", "transn", "zvv-vbz",
}


def canon(short_name):
    return {
        "liemobil": "VLM",
        "mobiju-pag": "PAG_MOBIJU",
        "ostwind-ab": "AB",
        "ostwind-vbsh": "VBSH",
        "tnw-aagl": "AAGL",
        "tnw-blt": "BLT",
        "tnw-bvb": "BVB",
        "tnw-pag": "PAG_TNW",
        "transn": "TRN",
        "zvv-vbz": "VBZ",
    }.get(short_name)


def main():
    text = urllib.request.urlopen(CSV_URL).read().decode()
    rows = list(csv.DictReader(io.StringIO(text)))

    generic = {}
    pag_mobiju = {}
    pag_tnw = {}

    for r in rows:
        short_name = r["shortOperatorName"]
        if short_name not in NETS:
            continue
        line = r["lineName"].strip()
        if is_train(short_name, line):
            continue
        val = {"bg": r["backgroundColor"].strip(), "fg": r["textColor"].strip()}
        border = r["borderColor"].strip()
        if border:
            val["border"] = border
        code = canon(short_name)
        if code == "PAG_MOBIJU":
            pag_mobiju[line] = val
        elif code == "PAG_TNW":
            pag_tnw[line] = val
        else:
            generic.setdefault(code, {})[line] = val

    data = {
        "LINE_COLORS": generic,
        "LINE_COLORS_PAG_MOBIJU": pag_mobiju,
        "LINE_COLORS_PAG_TNW": pag_tnw,
    }
    with open(OUT, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
