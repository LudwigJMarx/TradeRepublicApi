# Status (August 2026)

Trade Republic hat die Timeline umgestellt. `timelineTransactions` und
`timelineActivityLog` haben `timeline` ersetzt, die Eintraege sind flach statt
verschachtelt, Zeitstempel kommen als ISO-String und der Betrag steckt in
`amount`. `timelineDetailV2` liefert keine Felder mehr, sondern die
Beschreibung eines Bildschirms: Abschnitte mit beschrifteten Tabellenzeilen.

Alle Skripte hier sind darauf umgestellt. Die Auswertung steckt in
`trapi/timeline.py` und ist getestet; die Skripte hier sind nur noch das
Drumherum.

**Die ISIN kommt jetzt direkt aus der API.** Sie steht im Kopfabschnitt des
Details. Der ganze Umweg ueber Firmennamen entfaellt damit: `allStocks.json`,
`companyNameIsins.json` und die Meldung "WARNING: Company not found" braucht
niemand mehr.

`timelineCSVconvWithDetails.py` ist entfallen. Es tat dasselbe wie
`timelineCsvConverter.py`, nur mit Details - und der Konverter benutzt die
Details jetzt ohnehin. `envConsts.py` ist damit auch weg.

# Beispiele
Für diese Beispiele die Datei environment_template.py in environment.py umbenennen und die Trade Republic Login Daten eintragen.

# Export für Portfolio Performance
```bash
python3 timelineExporterWithDocsAndDetails.py
python3 timelineCsvConverter.py
```

Der erste Befehl meldet sich an, laedt die komplette Timeline samt Details und
speichert die angehaengten Dokumente in `./_docDownloads`. Der zweite braucht
keine Anmeldung und erzeugt `myTransactions.csv`.

Eintraege, deren `eventType` der Konverter nicht kennt, werden am Ende
aufgelistet statt stillschweigend weggelassen. Soll so eine Art in den Export,
gehoert sie in `EVENT_TYPES` in `trapi/timeline.py`. Dort steht auch `LABELS`
mit den Zeilenbeschriftungen, aus denen Stueckzahl, Kurs, Gebuehren und
Steuern gelesen werden - die haengen an der Sprache, in der die API antwortet.

## timelineExporterWithDocsAndDetails.py
Laedt Timeline und Details nach `myTimeline.json` und `myTimelineDetails.json`
und die Dokumente nach `./_docDownloads`. Bereits geladene Dokumente werden
uebersprungen.

## timelineCsvConverter.py
Erzeugt `myTransactions.csv` aus den beiden JSON-Dateien. Ohne
`myTimelineDetails.json` laeuft er ebenfalls, dann bleiben Stueckzahl, Kurs
und ISIN leer - die Timeline selbst kennt sie nicht.

## timelineExporter.py
Speichert nur die Timeline, ohne Details und Dokumente, nach
`myTimeline.json` und `myActivityLog.json`.

## portfolioExporter.py
Liest das aktuelle Portfolio von TR aus und speichert dieses als myPortfolio.json ab.

## isinDownloader.py
Fragt Stock Details ab. Fuer den CSV-Export wird das nicht mehr gebraucht, es
ist aber weiterhin nuetzlich, um Stammdaten zu sammeln.

usage: isinDownloader.py [-h] [-i ISIN] [-f FILE] [-p] [-c]

optional arguments:
-h, --help            show this help message and exit
-i ISIN, --isin ISIN  Crawl single ISIN
-f FILE, --file FILE  Crawl a list of ISINs
-p, --portfolio       Crawl all stocks from myPortfolio.json
-c, --combine         Combine all stock data to a single JSON file

```bash
python3 isinDownloader.py -i US72919P2020
python3 isinDownloader.py -f isins.txt
```
