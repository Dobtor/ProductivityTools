# OOXML 元素白名單

> 本檔由 `tools/scan_ooxml_elements.py` 自動產生，依 fixture 實際出現的元素統計。
> Parser 僅需實作此清單；超出範圍的元素先做 fallback 不擋上線。

**Fixture 總數**：42 份 DOCX
**唯一元素數**：392

## w: WordprocessingML（核心）（210 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `w:rsid` | 79621 | 42/42 |
| `w:rPr` | 18448 | 42/42 |
| `w:rFonts` | 17656 | 42/42 |
| `w:lsdException` | 14921 | 42/42 |
| `w:sz` | 11133 | 42/42 |
| `w:r` | 10782 | 42/42 |
| `w:t` | 10387 | 42/42 |
| `w:szCs` | 9507 | 42/42 |
| `w:pPr` | 8265 | 42/42 |
| `w:style` | 4159 | 42/42 |
| `w:name` | 4159 | 42/42 |
| `w:spacing` | 3979 | 42/42 |
| `w:jc` | 3815 | 42/42 |
| `w:p` | 3811 | 42/42 |
| `w:color` | 3784 | 42/42 |
| `w:ind` | 3672 | 38/42 |
| `w:basedOn` | 3493 | 42/42 |
| `w:proofErr` | 2958 | 35/42 |
| `w:qFormat` | 2880 | 40/42 |
| `w:autoSpaceDE` | 2781 | 21/42 |
| `w:autoSpaceDN` | 2724 | 33/42 |
| `w:kern` | 2681 | 42/42 |
| `w:tc` | 2611 | 39/42 |
| `w:tcPr` | 2611 | 39/42 |
| `w:tcW` | 2611 | 39/42 |
| `w:adjustRightInd` | 2475 | 32/42 |
| `w:vAlign` | 2410 | 39/42 |
| `w:right` | 2089 | 42/42 |
| `w:left` | 2005 | 42/42 |
| `w:bottom` | 1904 | 42/42 |
| `w:top` | 1798 | 42/42 |
| `w:lvl` | 1751 | 33/42 |
| `w:numFmt` | 1751 | 33/42 |
| `w:lvlText` | 1751 | 33/42 |
| `w:lvlJc` | 1751 | 33/42 |
| `w:start` | 1696 | 33/42 |
| `w:tcBorders` | 1238 | 35/42 |
| `w:b` | 1202 | 36/42 |
| `w:widowControl` | 1172 | 42/42 |
| `w:snapToGrid` | 1101 | 42/42 |
| `w:link` | 1070 | 40/42 |
| `w:gridSpan` | 1055 | 33/42 |
| `w:textAlignment` | 1002 | 30/42 |
| `w:tab` | 989 | 42/42 |
| `w:tr` | 669 | 39/42 |
| `w:trPr` | 668 | 39/42 |
| `w:next` | 668 | 40/42 |
| `w:trHeight` | 653 | 39/42 |
| `w:tabs` | 652 | 42/42 |
| `w:pBdr` | 574 | 14/42 |
| `w:font` | 554 | 42/42 |
| `w:charset` | 554 | 42/42 |
| `w:family` | 554 | 42/42 |
| `w:pitch` | 554 | 42/42 |
| `w:uiPriority` | 548 | 42/42 |
| `w:sig` | 524 | 42/42 |
| `w:bCs` | 505 | 28/42 |
| `w:keepNext` | 450 | 16/42 |
| `w:gridCol` | 421 | 39/42 |
| `w:noProof` | 415 | 24/42 |
| `w:shd` | 376 | 31/42 |
| `w:outlineLvl` | 356 | 17/42 |
| `w:panose1` | 346 | 42/42 |
| `w:lang` | 309 | 42/42 |
| `w:cantSplit` | 308 | 22/42 |
| `w:div` | 294 | 26/42 |
| `w:marLeft` | 294 | 26/42 |
| `w:marRight` | 294 | 26/42 |
| `w:marTop` | 294 | 26/42 |
| `w:marBottom` | 294 | 26/42 |
| `w:divBdr` | 294 | 26/42 |
| `w:vMerge` | 286 | 27/42 |
| `w:altName` | 269 | 42/42 |
| `w:bodyDiv` | 262 | 26/42 |
| `w:semiHidden` | 249 | 42/42 |
| `w:iCs` | 248 | 18/42 |
| `w:bdr` | 241 | 19/42 |
| `w:compatSetting` | 232 | 42/42 |
| `w:unhideWhenUsed` | 217 | 42/42 |
| `w:tblBorders` | 207 | 32/42 |
| `w:abstractNum` | 207 | 33/42 |
| `w:nsid` | 207 | 33/42 |
| `w:multiLevelType` | 207 | 33/42 |
| `w:tmpl` | 207 | 33/42 |
| `w:num` | 207 | 33/42 |
| `w:abstractNumId` | 207 | 33/42 |
| `w:insideH` | 206 | 32/42 |
| `w:insideV` | 206 | 32/42 |
| `w:tblPr` | 177 | 42/42 |
| `w:footnote` | 168 | 42/42 |
| `w:endnote` | 168 | 42/42 |
| `w:txbxContent` | 168 | 24/42 |
| `w:drawing` | 156 | 24/42 |
| `w:pStyle` | 155 | 33/42 |
| `w:bookmarkStart` | 126 | 20/42 |
| `w:bookmarkEnd` | 126 | 20/42 |
| `w:textDirection` | 120 | 16/42 |
| `w:tblPrEx` | 115 | 7/42 |
| `w:tblCellMar` | 104 | 42/42 |
| `w:tcMar` | 102 | 2/42 |
| `w:isLgl` | 98 | 14/42 |
| `w:u` | 96 | 30/42 |
| `w:numPr` | 90 | 29/42 |
| `w:numId` | 90 | 29/42 |
| `w:i` | 88 | 18/42 |
| `w:hideMark` | 87 | 2/42 |
| `w:separator` | 84 | 42/42 |
| `w:continuationSeparator` | 84 | 42/42 |
| `w:pict` | 84 | 24/42 |
| `w:footnotePr` | 76 | 42/42 |
| `w:tblInd` | 75 | 42/42 |
| `w:activeWritingStyle` | 75 | 16/42 |
| `w:tbl` | 71 | 39/42 |
| `w:tblW` | 71 | 39/42 |
| `w:tblLook` | 71 | 39/42 |
| `w:tblGrid` | 71 | 39/42 |
| `w:kinsoku` | 70 | 14/42 |
| `w:sectPr` | 62 | 42/42 |
| `w:pgSz` | 62 | 42/42 |
| `w:pgMar` | 62 | 42/42 |
| `w:cols` | 62 | 42/42 |
| `w:ilvl` | 62 | 29/42 |
| `w:br` | 60 | 22/42 |
| `w:tblLayout` | 55 | 35/42 |
| `w:lastRenderedPageBreak` | 52 | 32/42 |
| `w:suff` | 50 | 5/42 |
| `w:styles` | 48 | 42/42 |
| `w:docDefaults` | 48 | 42/42 |
| `w:rPrDefault` | 48 | 42/42 |
| `w:pPrDefault` | 48 | 42/42 |
| `w:latentStyles` | 48 | 42/42 |
| `w:numRestart` | 48 | 14/42 |
| `w:document` | 42 | 42/42 |
| `w:body` | 42 | 42/42 |
| `w:footnotes` | 42 | 42/42 |
| `w:endnotes` | 42 | 42/42 |
| `w:settings` | 42 | 42/42 |
| `w:zoom` | 42 | 42/42 |
| `w:bordersDoNotSurroundHeader` | 42 | 42/42 |
| `w:bordersDoNotSurroundFooter` | 42 | 42/42 |
| `w:defaultTabStop` | 42 | 42/42 |
| `w:characterSpacingControl` | 42 | 42/42 |
| `w:hdrShapeDefaults` | 42 | 42/42 |
| `w:endnotePr` | 42 | 42/42 |
| `w:compat` | 42 | 42/42 |
| `w:useFELayout` | 42 | 42/42 |
| `w:rsids` | 42 | 42/42 |
| `w:rsidRoot` | 42 | 42/42 |
| `w:themeFontLang` | 42 | 42/42 |
| `w:clrSchemeMapping` | 42 | 42/42 |
| `w:shapeDefaults` | 42 | 42/42 |
| `w:decimalSymbol` | 42 | 42/42 |
| `w:listSeparator` | 42 | 42/42 |
| `w:fonts` | 42 | 42/42 |
| `w:webSettings` | 42 | 42/42 |
| `w:spaceForUL` | 37 | 37/42 |
| `w:balanceSingleByteDoubleByteWidth` | 37 | 37/42 |
| `w:doNotLeaveBackslashAlone` | 37 | 37/42 |
| `w:ulTrailSpace` | 37 | 37/42 |
| `w:doNotExpandShiftReturn` | 37 | 37/42 |
| `w:proofState` | 35 | 35/42 |
| `w:displayHorizontalDrawingGridEvery` | 35 | 35/42 |
| `w:pgNumType` | 34 | 14/42 |
| `w:titlePg` | 34 | 14/42 |
| `w:doNotIncludeSubdocsInStats` | 33 | 33/42 |
| `w:numbering` | 33 | 33/42 |
| `w:vertAlign` | 32 | 24/42 |
| `w:divsChild` | 32 | 4/42 |
| `w:w` | 31 | 9/42 |
| `w:docGrid` | 29 | 29/42 |
| `w:vanish` | 28 | 14/42 |
| `w:overflowPunct` | 28 | 14/42 |
| `w:embedSystemFonts` | 26 | 26/42 |
| `w:drawingGridHorizontalSpacing` | 26 | 26/42 |
| `w:divs` | 26 | 26/42 |
| `w:highlight` | 25 | 9/42 |
| `w:stylePaneFormatFilter` | 25 | 25/42 |
| `w:suppressAutoHyphens` | 24 | 12/42 |
| `w:gridAfter` | 24 | 4/42 |
| `w:wAfter` | 24 | 4/42 |
| `w:displayVerticalDrawingGridEvery` | 23 | 23/42 |
| `w:adjustLineHeightInTable` | 23 | 23/42 |
| `w:relyOnVML` | 22 | 22/42 |
| `w:allowPNG` | 22 | 22/42 |
| `w:strike` | 19 | 6/42 |
| `w:tblStyle` | 17 | 17/42 |
| `w:optimizeForBrowser` | 16 | 16/42 |
| `w:framePr` | 16 | 14/42 |
| `w:hideSpellingErrors` | 14 | 14/42 |
| `w:hideGrammaticalErrors` | 14 | 14/42 |
| `w:doNotHyphenateCaps` | 14 | 14/42 |
| `w:drawingGridVerticalSpacing` | 14 | 14/42 |
| `w:doNotShadeFormData` | 14 | 14/42 |
| `w:smallCaps` | 14 | 14/42 |
| `w:caps` | 14 | 14/42 |
| `w:locked` | 14 | 14/42 |
| `w:wordWrap` | 14 | 14/42 |
| `w:topLinePunct` | 14 | 14/42 |
| `w:footerReference` | 9 | 9/42 |
| `w:ftr` | 9 | 9/42 |
| `w:noWrap` | 9 | 2/42 |
| `w:headerReference` | 7 | 7/42 |
| `w:hdr` | 7 | 7/42 |
| `w:tblpPr` | 7 | 7/42 |
| `w:position` | 6 | 3/42 |
| `w:rStyle` | 5 | 1/42 |
| `w:tblOverlap` | 5 | 5/42 |
| `w:autoHyphenation` | 5 | 5/42 |
| `w:documentProtection` | 2 | 2/42 |
| `w:noPunctuationKerning` | 2 | 2/42 |

## a: DrawingML 主（81 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `a:font` | 2522 | 42/42 |
| `a:srgbClr` | 674 | 42/42 |
| `a:schemeClr` | 668 | 42/42 |
| `a:satMod` | 496 | 42/42 |
| `a:gs` | 454 | 42/42 |
| `a:ext` | 379 | 26/42 |
| `a:solidFill` | 350 | 42/42 |
| `a:shade` | 286 | 42/42 |
| `a:noFill` | 286 | 26/42 |
| `a:ln` | 279 | 42/42 |
| `a:tint` | 256 | 42/42 |
| `a:avLst` | 167 | 24/42 |
| `a:gradFill` | 164 | 42/42 |
| `a:gsLst` | 164 | 42/42 |
| `a:extLst` | 160 | 23/42 |
| `a:graphic` | 156 | 24/42 |
| `a:graphicData` | 156 | 24/42 |
| `a:xfrm` | 156 | 24/42 |
| `a:off` | 156 | 24/42 |
| `a:prstGeom` | 156 | 24/42 |
| `a:graphicFrameLocks` | 145 | 24/42 |
| `a:effectLst` | 129 | 42/42 |
| `a:prstDash` | 126 | 42/42 |
| `a:effectStyle` | 126 | 42/42 |
| `a:outerShdw` | 118 | 42/42 |
| `a:alpha` | 118 | 42/42 |
| `a:miter` | 89 | 25/42 |
| `a:lin` | 88 | 42/42 |
| `a:sysClr` | 84 | 42/42 |
| `a:latin` | 84 | 42/42 |
| `a:ea` | 84 | 42/42 |
| `a:cs` | 84 | 42/42 |
| `a:rot` | 76 | 38/42 |
| `a:path` | 76 | 38/42 |
| `a:fillToRect` | 76 | 38/42 |
| `a:spLocks` | 73 | 24/42 |
| `a:blip` | 72 | 16/42 |
| `a:stretch` | 72 | 16/42 |
| `a:fillRect` | 71 | 16/42 |
| `a:headEnd` | 70 | 21/42 |
| `a:tailEnd` | 70 | 21/42 |
| `a:noAutofit` | 59 | 19/42 |
| `a:picLocks` | 52 | 11/42 |
| `a:theme` | 42 | 42/42 |
| `a:themeElements` | 42 | 42/42 |
| `a:clrScheme` | 42 | 42/42 |
| `a:dk1` | 42 | 42/42 |
| `a:lt1` | 42 | 42/42 |
| `a:dk2` | 42 | 42/42 |
| `a:lt2` | 42 | 42/42 |
| `a:accent1` | 42 | 42/42 |
| `a:accent2` | 42 | 42/42 |
| `a:accent3` | 42 | 42/42 |
| `a:accent4` | 42 | 42/42 |
| `a:accent5` | 42 | 42/42 |
| `a:accent6` | 42 | 42/42 |
| `a:hlink` | 42 | 42/42 |
| `a:folHlink` | 42 | 42/42 |
| `a:fontScheme` | 42 | 42/42 |
| `a:majorFont` | 42 | 42/42 |
| `a:minorFont` | 42 | 42/42 |
| `a:fmtScheme` | 42 | 42/42 |
| `a:fillStyleLst` | 42 | 42/42 |
| `a:lnStyleLst` | 42 | 42/42 |
| `a:effectStyleLst` | 42 | 42/42 |
| `a:bgFillStyleLst` | 42 | 42/42 |
| `a:objectDefaults` | 42 | 42/42 |
| `a:extraClrSchemeLst` | 42 | 42/42 |
| `a:scene3d` | 38 | 38/42 |
| `a:camera` | 38 | 38/42 |
| `a:lightRig` | 38 | 38/42 |
| `a:sp3d` | 38 | 38/42 |
| `a:bevelT` | 38 | 38/42 |
| `a:spAutoFit` | 32 | 9/42 |
| `a:lumMod` | 32 | 4/42 |
| `a:srcRect` | 27 | 13/42 |
| `a:prstTxWarp` | 11 | 11/42 |
| `a:txDef` | 7 | 7/42 |
| `a:spPr` | 7 | 7/42 |
| `a:bodyPr` | 7 | 7/42 |
| `a:lstStyle` | 7 | 7/42 |

## wp: DrawingML Word 內嵌（11 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `wp:posOffset` | 168 | 24/42 |
| `wp:extent` | 156 | 24/42 |
| `wp:effectExtent` | 156 | 24/42 |
| `wp:docPr` | 156 | 24/42 |
| `wp:cNvGraphicFramePr` | 156 | 24/42 |
| `wp:anchor` | 84 | 24/42 |
| `wp:simplePos` | 84 | 24/42 |
| `wp:positionH` | 84 | 24/42 |
| `wp:positionV` | 84 | 24/42 |
| `wp:wrapNone` | 84 | 24/42 |
| `wp:inline` | 72 | 16/42 |

## pic: DrawingML Picture（6 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `pic:pic` | 72 | 16/42 |
| `pic:nvPicPr` | 72 | 16/42 |
| `pic:cNvPr` | 72 | 16/42 |
| `pic:cNvPicPr` | 72 | 16/42 |
| `pic:blipFill` | 72 | 16/42 |
| `pic:spPr` | 72 | 16/42 |

## m: Math (OMML)（12 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `m:mathPr` | 42 | 42/42 |
| `m:mathFont` | 42 | 42/42 |
| `m:brkBin` | 42 | 42/42 |
| `m:brkBinSub` | 42 | 42/42 |
| `m:smallFrac` | 42 | 42/42 |
| `m:dispDef` | 42 | 42/42 |
| `m:lMargin` | 42 | 42/42 |
| `m:rMargin` | 42 | 42/42 |
| `m:defJc` | 42 | 42/42 |
| `m:wrapIndent` | 42 | 42/42 |
| `m:intLim` | 42 | 42/42 |
| `m:naryLim` | 42 | 42/42 |

## v: VML（舊式向量圖）（7 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `v:textbox` | 84 | 24/42 |
| `v:shape` | 64 | 19/42 |
| `v:rect` | 20 | 5/42 |
| `v:shapetype` | 19 | 19/42 |
| `v:stroke` | 19 | 19/42 |
| `v:path` | 19 | 19/42 |
| `v:fill` | 10 | 5/42 |

## o: Office VML 擴展（3 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `o:shapedefaults` | 84 | 42/42 |
| `o:shapelayout` | 42 | 42/42 |
| `o:idmap` | 42 | 42/42 |

## w14: Word 2010 擴展（1 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `w14:docId` | 28 | 28/42 |

## w15: Word 2012 擴展（2 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `w15:docId` | 36 | 36/42 |
| `w15:chartTrackingRefBased` | 2 | 2/42 |

## mc: Markup Compatibility（3 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `mc:AlternateContent` | 84 | 24/42 |
| `mc:Choice` | 84 | 24/42 |
| `mc:Fallback` | 84 | 24/42 |

## {http: {http（56 個元素）

| 元素 | 總出現次數 | 出現於檔數 |
|------|-----------|------------|
| `{http://schemas.openxmlformats.org/package/2006/content-types}Override` | 560 | 42/42 |
| `{http://schemas.openxmlformats.org/package/2006/content-types}Default` | 101 | 42/42 |
| `{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}wsp` | 84 | 24/42 |
| `{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}cNvSpPr` | 84 | 24/42 |
| `{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}spPr` | 84 | 24/42 |
| `{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}txbx` | 84 | 24/42 |
| `{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}bodyPr` | 84 | 24/42 |
| `{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}sizeRelH` | 84 | 24/42 |
| `{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}pctWidth` | 84 | 24/42 |
| `{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}sizeRelV` | 84 | 24/42 |
| `{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}pctHeight` | 84 | 24/42 |
| `{http://schemas.microsoft.com/office/drawing/2010/main}useLocalDpi` | 72 | 16/42 |
| `{http://schemas.microsoft.com/office/drawing/2010/main}hiddenFill` | 63 | 21/42 |
| `{http://schemas.microsoft.com/office/drawing/2010/main}hiddenLine` | 63 | 21/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/customXml}datastoreItem` | 60 | 36/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/customXml}schemaRefs` | 60 | 36/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/customXml}schemaRef` | 60 | 36/42 |
| `{http://schemas.openxmlformats.org/package/2006/content-types}Types` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Properties` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Template` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}TotalTime` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Pages` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Words` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Characters` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Application` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}DocSecurity` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Lines` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Paragraphs` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}ScaleCrop` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Company` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}LinksUpToDate` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}CharactersWithSpaces` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}SharedDoc` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}HyperlinksChanged` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}AppVersion` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}coreProperties` | 42 | 42/42 |
| `{http://purl.org/dc/elements/1.1/}creator` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}revision` | 42 | 42/42 |
| `{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastPrinted` | 42 | 42/42 |
| `{http://purl.org/dc/terms/}created` | 42 | 42/42 |
| `{http://purl.org/dc/terms/}modified` | 42 | 42/42 |
| `{http://purl.org/dc/elements/1.1/}title` | 40 | 40/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}property` | 38 | 25/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes}lpwstr` | 38 | 25/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/bibliography}Sources` | 36 | 36/42 |
| `{http://schemas.openxmlformats.org/officeDocument/2006/custom-properties}Properties` | 25 | 25/42 |
| `{http://www.wps.cn/officeDocument/2013/wpsCustomData}customData` | 24 | 24/42 |
| `{http://www.wps.cn/officeDocument/2013/wpsCustomData}customSectProps` | 24 | 24/42 |
| `{http://www.wps.cn/officeDocument/2013/wpsCustomData}customSectPr` | 24 | 24/42 |
| `{http://schemas.microsoft.com/office/drawing/2010/main}shadowObscured` | 21 | 12/42 |
| `{http://www.wps.cn/officeDocument/2013/wpsCustomData}customShpExts` | 5 | 5/42 |
| `{http://www.wps.cn/officeDocument/2013/wpsCustomData}customShpInfo` | 5 | 5/42 |
| `{http://schemas.microsoft.com/office/thememl/2012/main}themeFamily` | 4 | 4/42 |
| `{http://purl.org/dc/elements/1.1/}subject` | 2 | 2/42 |
| `{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}keywords` | 2 | 2/42 |
