***SYNTAX marked-en***

# Beispielprojekt

Arbeite im gemeinsamen Projektworkspace und berücksichtige frühere Ergebnisse.
Dokumentiere Fragen mit Datum/Zeit in `todo_fragen.md`. Der Agent schreibt keine
`process_stop`-Datei und setzt keine Status auf DONE. Er dokumentiert auch bei
Fehlern oder qualifiziertem Ergebnis vollständig; der Controller prüft den Status.
Korrigiere lokale Fehler innerhalb des jeweiligen Auftrags und dokumentiere sie.

***CFG network_access=false web_search=disabled***
1. ***Task***: Erstelle die UTF-8-Datei `beispiel.txt` mit genau einer Zeile `Hallo ARQUILO!` und dokumentiere das Ergebnis in `todo_result_1.md`.
    Abnahme: Die Datei enthält genau den vorgegebenen Text mit abschließendem Zeilenumbruch. Ergebnisbericht mit tatsächlichem Dateivergleich.

***CFG network_access=false web_search=disabled***
2. ***Task***: Prüfe `beispiel.txt` und das frühere Ergebnis; dokumentiere den Befund in `todo_result_2.md`.
    Abnahme: Der Bericht nennt tatsächlichen Inhalt und Abweichungen; lokal begrenzte Abweichungen sind korrigiert und erneut geprüft.
