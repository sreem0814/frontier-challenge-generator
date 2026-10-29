#!/usr/bin/env bash
# lo_convert.sh <dir>: convert every *-xw.xlsx and *-xw.xlsm in <dir> with LibreOffice (formulas recalculated on load)
# into -lo.xlsx, -lo8.xls (BIFF8), -lo5.xls (BIFF5) and -lo.ods.
set -euo pipefail
D="$1"
PROFILE=/tmp/lo-profile
mkdir -p "$PROFILE/user"
cat > "$PROFILE/user/registrymodifications.xcu" <<'XCU'
<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Load"><prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>
</oor:items>
XCU
T=$(mktemp -d)
convert() { # convert <filter> <ext> <suffix>
  rm -rf "$T/out"; mkdir -p "$T/out"
  soffice --headless --norestore -env:UserInstallation=file://$PROFILE --convert-to "$2:$1" --outdir "$T/out" "$D"/*-xw.xls[xm] >/dev/null 2>&1 || true
  for f in "$T/out"/*; do
    [ -e "$f" ] || continue
    b=$(basename "$f"); b=${b%-xw.*}
    mv "$f" "$D/$b$3"
  done
}
convert "Calc MS Excel 2007 XML" xlsx -lo.xlsx
convert "MS Excel 97" xls -lo8.xls
convert "MS Excel 95" xls -lo5.xls
convert "calc8" ods -lo.ods
rm -rf "$T"
