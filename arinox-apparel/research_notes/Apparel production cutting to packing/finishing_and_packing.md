# Finishing and Packing of Woven Garments for US/Canada Brands (Vietnam export factory, FOB/DDP)

Scope: from end of sewing (or after wash) through finishing, trims, packing, carton labelling and the packing list / ASN. Written for an ERP designer. Every sourced claim has an inline link. Statements in "Inferences" are the researcher's synthesis or common industry practice that I could not tie to a specific source; treat them as design proposals to confirm with buyers.

Source-quality note: most apparel-process sources are practitioner blogs (onlineclothingstudy.com), Scribd uploads or vendor marketing. Primary sources reached: GS1 (support pages, GS1 UK/AU, GSCN 19-059), Canada Competition Bureau, ERPNext docs, retailer vendor manuals (Foot Locker, DSW/Designer Brands, Kohl's via search snippets only, as kohls.com returned HTTP 403). State polybag statutes were NOT read directly; figures come from a compliance aggregator.

## 1. Finishing sequence, inspection, metal detection and counting

### Takeaway
Finishing is a fixed sequence: trim, check, attach buttons/trims, spot clean, repair, press, final check, fold/tag, metal detect, pack. It is inspected 100% (initial check before pressing, final check after) with hourly logs of defects and rework. Needle detection follows the buyer's own broken-needle policy. The usual calibration is a 1.2 mm ferrous test piece checked at start-up and at set intervals, with records kept for at least 1 year. Output must be split into passed (A-grade), in rework/alter, B-grade/seconds and reject. No single standard formula exists for this split.

### Cited Findings
- Finishing-department steps listed in order: (1) thread trimming by helpers, since "uncut and loose threads on garments are considered defects"; (2) garment checking inside and out for visual quality, measurements, care labels and trims; (3) button attachment and buttonholing (buttons, snaps, eyelets); (4) stain removal with a spot gun or stain-removal machine before pressing, and some garments are washed in finishing; (5) repair/mending in finishing rather than back in sewing; (6) ironing/pressing with steam irons and vacuum tables; (7) folding to set dimensions, with price/hang tags attached by kimble (tag) gun or thread; (8) polybag and carton packing to customer requirements; (9) the packing in-charge prepares the packing list and tells the merchandiser once the order is packed; (10) internal shipment audit by QA before final inspection; (11) pressing and packing production records — [onlineclothingstudy: Functions of finishing department](https://www.onlineclothingstudy.com/2015/10/functions-of-finishing-department-in.html)
- Simple flow: Cutting → Stitching → Finishing → Ironing → Needle Detection → Packing. Needle detectors usually sit at final inspection, just before packaging — [onlineclothingstudy: finishing tools](https://www.onlineclothingstudy.com/2017/06/finishing-tools-machines-and-equipment.html); [boonbac blog (vendor)](https://boonbac.com/read-blog/30843_needle-detector-how-metal-detection-ensures-safety-in-garment-manufacturing.html)
- Two inspection points: "initial finishing inspection" before pressing, and "final finishing inspection" after pressing, after which garments are "passed for tagging and packing" — [Scribd: Garments Inspection](https://www.scribd.com/document/425076032/Garments-Inspection) (practitioner upload)
- Hourly control: "Hourly quality inspection report to be maintained by Q.I's… Finishing Q.C and Finishing supervisor have to note defect and rework quantities hourly basis"; hourly production records go to the finishing in-charge — [Scribd: Finishing SOP](https://www.scribd.com/document/905772998/Finishing-Sop) (factory SOP upload)
- Defect tagging on the floor: fabric defects are marked with stickers, and alteration pieces are marked by knotting at the spot to be fixed — [Scribd: Alter defects](https://www.scribd.com/document/428640699/Alter-defects-pdf)
- Factory roles track "alter, B [grade] & wastage %" and close alteration and B-grade pieces daily — [mustakbil job listing](https://www.mustakbil.com/jobs/job/176394)
- Defect % is measured hourly and daily. DHU (defects per hundred units) is the standard metric, and lower is better — [Scribd: Rework minimization](https://www.scribd.com/presentation/31213309/Rework-minimization)
- Metal detection is governed by the buyer's broken-needle / sharp-metal policy, available from the buyer or buying house — [onlineclothingstudy: Broken needle policy](https://www.onlineclothingstudy.com/2019/11/broken-needle-policy-for-garment.html)
- Audit checklist item: "Is the metal detector calibrated every time it is switched on, and at regular frequency (with 1.2 mm calibration piece)?" and "Are calibration records kept for at least 1 year?" — [QIMA SAQ non-food textile add-on](https://saq.qima.com/Non-FoodTextileAdd-on)
- Practitioner policy: 1.2 mm calibration card checked about every 2 hours. If the check fails, re-check all garments passed since the last good test — [Scribd: Broken Needle Policy](https://www.scribd.com/doc/188831889/20348663-Broken-Needle-Policy)
- Best achievable sensitivity is about a 1.2 mm ferrous sphere, which roughly equals a 1 mm × 1.2 mm broken needle fragment — [Textile World 2018](https://www.textileworld.com/textile-world/2018/08/using-metal-detectors-and-magnetic-separators-to-ensure-textile-product-safety/)
- Detectors offer Fe 0.8 / 1.0 / 1.2 mm test modes. "Not every garment factory requires exactly the same sensitivity." Missing needle-detection, calibration or broken-needle records "may affect approval of inspection or shipment" — [Oshima blog (machine vendor)](https://www.oshima.com.tw/blog/needle-detector-garment-export-quality-control)
- Kohl's publishes a dedicated Broken Needle Policy for vendors (not readable: HTTP 403) — [Kohl's Broken Needle Policy PDF](https://link.kohls.com/content/dam/klink/pdfs/Broken%20Needle%20Policy.pdf)
- Common reasons garments fail needle detection (metal trims, staples, pins, etc.) are discussed in — [fibre2fashion](https://www.fibre2fashion.com/industry-article/8117/why-garments-fail-the-needle-detection?amp=true)
- Older definition: any fault on a finished garment makes it a "seconds" piece. This is a garment count, not a defect count — [Scribd: Garments Inspection](https://www.scribd.com/document/425076032/Garments-Inspection)

### Inferences
- **ERP documents suggested:** Finishing Receipt (from sewing or washing), Finishing Hourly QC (grid: hour × checked / passed / defect by code / sent to rework / rework returned / B-grade), Needle Detector Log (machine, calibration piece size, check time, pass/fail, garments re-checked), Broken Needle Log (operator, line, time, needle fragments found yes/no, all pieces recovered yes/no, supervisor sign-off), and Finishing Output (A-grade passed to packing).
- **Counting rule:** Received = Passed (A) + In rework (WIP) + B-grade + Reject/Scrap + Missing. Reworked pieces re-enter the inspection queue. Count them once in "checked", or track first-pass yield separately (FPY = passed first time ÷ checked first time). DHU = total defects ÷ pieces checked × 100. Defect % = defective pieces ÷ checked × 100.
- **Metal detector rule:** If a calibration check fails, quarantine everything passed since the last good check and re-scan it. A garment that triggers the detector is held, X-rayed or opened, and logged. It must never be packed. Children's wear often requires 100% detection (common buyer practice; confirm per buyer).
- **Labels after wash (garment-dyed or washed wovens):** Practice is to sew neck/main, size and care labels at finishing, after washing. Wash can fade or shrink labels and abrade print, and size or wash-code labels may only be confirmed after post-wash measurement. This is inferred, as no source confirmed it (see Gaps). Track it as a finishing operation that consumes label trims.
- **Measurement check:** After pressing (and after wash for washed styles), sample per size against the spec sheet with tolerances. Record it as a measurement QC record per size with a pass/fail per point of measure (POM).

### Gaps
- No authoritative source explaining why labels are attached after wash. This is common practice, but unsourced.
- No standard formula for netting finishing output against rework and B-grade. Factories define their own.
- Kohl's and other retailer broken-needle policies were not readable (403). Buyer-specific test sizes are therefore not confirmed.
- Disposal and sale rules for B-grade (brand-label removal, destruction certificates) were not researched.

## 2. Trims applied at finishing/packing (hang tags, UPC/GTIN, RFID, polybags, folding)

### Takeaway
Every style-colour-size (SKU) needs its own GTIN (UPC-A in the US). The barcode, price ticket and RFID tag are SKU-level trims that must match the PO. Polybag suffocation warnings are required by several US states (CA, NY, MA, VA, RI, plus NYC and Chicago) for film under 1 mil (0.001 in) above certain sizes. Minimum font size grows with bag size, from 10 pt up to 36 pt in Virginia. Retailer and Amazon rules can be stricter, for example a 5-inch opening trigger.

### Cited Findings
- GS1: "every variation of your product (e.g. each size, each colour) requires its unique GS1 GTIN"; "One GS1 GTIN can only be assigned to one product" — [GS1 support: GTINs for sizes and colours](https://support.gs1.org/support/solutions/articles/43000734083-how-many-gs1-gtins-do-i-need-when-i-have-a-product-with-many-sizes-and-colours-)
- Apparel practice is one GTIN per style-colour-size. A common mistake is giving one barcode to every size and colour — [WavePLM blog](https://blog.waveplm.com/gs1-gtin-for-fashion-brands-how-to-get-barcodes-register-products-and-stay-retail-ready/); [SPS Commerce: UPC, GTIN and style number basics](https://www.spscommerce.com/community/articles/upc-gtin-and-style-number-basics-for-apparel-and-footwear)
- States with polybag suffocation-warning laws: Massachusetts, California, New York, Rhode Island, Virginia, plus New York City and Chicago — [EcoEnclose help](https://help.ecoenclose.com/en-US/what-are-poly-bag-suffocation-requirements-185611)
- State triggers (aggregator, statutes not verified):
  - **CA:** film under 0.001 in; opening over 25 sq in; capacity over 125 cu in; font 10 pt when L+W is under 30 in; must be printed by offset or letterpress; exemption for industrial-only bags.
  - **NY:** under 0.001 in; L+W of 25 in or more; opening side over 7 in; 24 pt when L+W is 60 in or more.
  - **MA:** under 1 mil; L+W of 25 in or more; 18 pt for L+W of 40 to under 60 in; warning must be repeated when L and W exceed 40 in.
  - **VA:** dry-cleaning (fresh clothing) bags; at least 36 pt.
  - **RI:** opening over 5 in; boldface type.
  - **All states:** warning goes in a conspicuous place on the bag or on an attached label.
  - Source: [ComplianceGate: Bag suffocation warning](https://www.compliancegate.com/bag-suffocation-warning/)
- Amazon: warning required on poly bags with an opening of 5 in or more. Font bands by L+W: under 29 in = 10 pt, 30–39 = 14 pt, 40–49 = 18 pt, 60+ = 24 pt. The aggregator gives no band for 50–59 — [ComplianceGate](https://www.compliancegate.com/bag-suffocation-warning/)
- Walmart and Amazon reportedly require a warning on any polybag with an opening of 5 in or larger. Target's hard-goods standard requires at least 20 pt (vendor blog; not verified in retailer documents) — [EcoEnclose blog](https://ecoenclose.com/blog/suffocation-warnings-legal-packaging-requirements); [Interplas](https://www.interplas.com/suffocation-warning-bags)
- Massachusetts reportedly needs government approval for any wording beyond the statutory text — [EcoEnclose blog](https://www.ecoenclose.com/blog/suffocation-warnings-packaging-requirements-legal-guidelines-to-know/)
- Folding / pack styles:
  - flat fold in polybag
  - folded in individual box (e.g. men's shirts)
  - unfolded on a hanger in a hanger bag
  - unfolded loose in the carton
  - crash fold (shorts, boxers, cargo pants)
  - blister pack (several garments in one polybag in a set size/colour ratio)
  - Source: [onlineclothingstudy: Types of garment packing](https://www.onlineclothingstudy.com/2016/11/different-types-of-garment-packing.html)
- Canada (Textile Labelling Act): generic fibre names and fibre content must be in both English and French. Dealer identity (name and address, or CA number) and country of origin need not be bilingual. Care labelling is voluntary but must be accurate if given. Non-permanent labels (hang tags, stickers) are allowed only for some categories. Permanent labels must stay legible through at least 10 cleanings. Mislabelled imports may be relabelled in Canada only after notifying a Competition Bureau inspector — [Competition Bureau: labelling in a nutshell](https://competition-bureau.canada.ca/en/labelling/textile-labelling/labelling-textile-requirements-nutshell); [Competition Bureau: textile labelling requirements](https://competition-bureau.canada.ca/labelling/textile-labelling/textile-labelling-requirements); [Textile Labelling and Advertising Regulations C.R.C. c.1551](https://www.laws-lois.justice.gc.ca/eng/regulations/C.R.C.,_c._1551/page-1.html)
- Quebec has extra French-language rules for written information — [Competition Bureau](https://competition-bureau.canada.ca/labelling/textile-labelling/textile-labelling-requirements)

### Inferences
- **Trim master:** Model trims as items tagged with a trim type (hang tag, price ticket, UPC sticker, RFID tag, polybag, tissue, hanger, size clip or strip, silica gel, carton sticker), a consumption basis (per piece, per pack or per carton) and an SKU-variant flag. SKU-variant trims (price ticket, UPC, RFID, size strip) need a size × colour × PO consumption matrix and a GTIN check (the GTIN printed must match the GTIN on the PO line).
- **Polybag spec fields:** length, width, gusset, thickness (mil or micron; 1 mil = 25.4 µm), material (LDPE/recycled), warning text, language(s), font pt, printing method, vent/punch holes (yes/no, count, diameter), self-seal or adhesive flap, and a recycled-content claim. Add a rule: if thickness is under 1 mil and the size crosses a state threshold, warning text plus a minimum pt are required.
- **Price tickets and RFID tags** are often buyer-nominated, printed by a nominated vendor (e.g. a label service bureau) from PO data, and are a frequent late-arrival risk. Model them with expected-arrival dates linked to the T&A plan.
- **Canada orders:** a separate label set (bilingual fibre content, CA number), so a label BOM variant by ship-to country.

### Gaps
- Exact statutory warning text for each state, and current (2024–2026) amendments, were not read from primary statutes.
- No authoritative source on polybag hole-punch rules. ComplianceGate says this is unclear. Hole punching (vent holes) is a common buyer requirement but unsourced here.
- ASTM D3951 (commercial packaging practice) and CPSIA do not appear to mandate polybag warnings for apparel. Not verified.
- RFID (EPC/RAIN, GS1 SGTIN-96 encoding, retailer mandates such as Walmart's apparel RFID mandate) was not researched in this pass.
- Silica gel, tissue, hanger specs (e.g. VICS/retailer hanger programmes) and size-strip conventions were not found.

## 3. Packing methods, packing instructions, packing list, carton marks, GS1-128/SSCC, ASN, carton quality

### Takeaway
There are three carton types:
- **Solid:** one colour, one size per carton.
- **Ratio/assorted size:** one colour, sizes in a fixed ratio, e.g. S:M:L:XL = 5:7:7:5.
- **Mixed:** assorted colours and sizes in a ratio.

The buyer's packing instruction sets pcs per carton, ratio, folding and polybag. The packing list itemises each carton range with size breakdown, quantity, net/gross weight, dimensions and CBM. Each carton gets a unique SSCC-18 in a GS1-128 barcode. The SSCC must exactly match the EDI 856 ASN, and mismatches are the main chargeback driver. Retailer cartons are commonly capped at 50 lb (about 22.7 kg), sometimes 60 lb, with 200 lb burst or 32 ECT corrugate.

### Cited Findings
- Solid packing: one colour, one size per carton (e.g. 20 navy shirts in size S). Ratio (assorted) packing: one colour, multiple sizes in a set ratio (S:M:L:XL = 5:7:7:5). Mixed: multiple colours and/or sizes in a set ratio. For export orders the buyer specifies the packing method, and the ratio depends on market and order booking — [onlineclothingstudy: Types of garment packing](https://www.onlineclothingstudy.com/2016/11/different-types-of-garment-packing.html)
- Packing list layout: pieces per carton, number of cartons, total pieces, net and gross weight per carton, dimensions in cm and CBM per line. Total net weight on the packing list must match the bill of lading — [onlinegarmentsacademy: packing list](https://onlinegarmentsacademy.blogspot.com/2020/07/packing-list.html); [apparelandgarmentsbusiness blog 2026](https://apparelandgarmentsbusiness.blogspot.com/2026/05/packing-list-preparation-guide-for.html)
- SSCC structure: AI (00) + extension digit + GS1 company prefix (4–12 digits) + serial reference + check digit, 18 digits in total. It "can never be reused" and must match electronic documents exactly. Labels must not cross seams, wrap corners or be covered by tape. A "case pack defect" is an inner-pack barcode visible on the outside of a master carton — [SPS Commerce: GS1-128, SSCC, label placement](https://www.spscommerce.com/community/articles/labeling-for-new-suppliers-gs1-128-sscc-and-where-labels-have-to-go)
- GS1: "each logistic unit must be identified with a unique serial number, the SSCC". The SSCC carries no content information itself; it links to systems that hold it (ASN) — [GS1 Logistic Label Guideline r1.3 (2019)](https://www.gs1.org/standards/gs1-logistic-label-guideline); [GS1 UK how-to guide](https://www.gs1uk.org/sites/default/files/94702_HowToGuideslogistics%20labels%20and%20SSCCs_0315_FV.pdf)
- Label placement:
  - Carton barcode bottom edge at about 32 mm above the base (GS1 AU: "exactly 32 mm"; GS1 UK: no lower than 32 mm).
  - Barcode, including quiet zones, at least 50 mm from a vertical edge (GS1 UK). GS1 AU gives 19 mm for cartons. This conflicts; confirm per retailer.
  - Two identical labels on adjacent sides (short side + right-hand adjacent side) are recommended "if possible".
  - Most companies use A5 labels. US retail practice is 4×6 in (not sourced here).
  - Sources: [GS1 AU fact sheet](https://www.gs1au.org/download/GS1au-fact-sheet-logistic-labels.pdf/file); [GS1 UK pallet label best practice](https://www.gs1uk.org/knowledge-hub/barcodes/where-should-pallet-labels-be-placed); [GS1 GSCN 19-059 label placement](https://www.gs1.org/docs/barcodes/GSCN_19-059_label_placement.pdf)
- HBC: each SSCC-18 on the ASN must be unique to each carton with a valid check digit, and labels are approved during EDI testing — [HBC vendor standards: GS1-128 label requirements](https://sites.google.com/hbc.com/hbc-vendor-standards/edi-requirements/gs1-128-label-requirements)
- Dick's: "UCC-128 label must be accompanied by a valid 856 ASN or the label cannot be used" — [Dick's UCC128 label requirements](https://edi.jobisez.com/edi-igs/Dicks%20Sporting%20Goods/DICKS_UCC128%20Label%20Requirements.pdf)
- JCPenney: the SSCC-18 on the 856 must match the GS1-128 label exactly, with per-ship-point label certification — [Endless Commerce: JCPenney EDI](https://endlesscommerce.com/edi/requirements/jcpenney/)
- Meijer: carton barcodes are referenced in the 856 MAN (Marks and Numbers) segment — [Stacksync: Meijer 856](https://www.stacksync.com/edi/meijer/856)
- Best practice: SSCC generation, label printing and ASN generation should all read from the same data, so the label printed is the SSCC in the ASN — [Racklify: ASN labels](https://racklify.com/encyclopedia/how-warehouse-teams-should-create-asn-labels-for-retail-compliance/)
- UCC-128 is the old name for GS1-128 — [Endless Commerce: GS1-128](https://endlesscommerce.com/barcodes/gs1-128/)
- Carton limits:
  - Foot Locker: each carton must not exceed 50 lb; apparel corrugate at least 29 lb/in ECT (32 for footwear) — [Foot Locker 2024 VSM Section 06](https://www.footlocker-inc.com/content/dam/flincfoundation/footlockerinc_documents/vms/europe/2022/2024-Section-06.pdf)
  - Kohl's: 50 lb maximum, 3 lb minimum (search snippet; PDF returned 403) — [Kohl's Packaging & Shipping Requirements](https://link.kohls.com/content/dam/klink/pdfs/Kohls-Packaging-and-Shipping-Requirements.pdf)
  - DSW/Designer Brands: RSC with 200 lb burst or 32 lb ECT; maximum carton weight 60 lb (27.27 kg) in one version and 50 lb in another — [DSW carton spec 2023](https://images.dsw.ca/is/content/dswca/S7_0_Carton_Specifications_2023); [Designer Brands carton spec](https://www.designerbrands.com/media/1663/carton-specifications.pdf)
  - Akira: 50 lb maximum — [Akira vendor guide](https://www.shopakira.com/vendor-guide/packing)
- 200 lb burst does not automatically equal 32 ECT (commercial blog) — [Alibaba seller blog 2026](https://seller.alibaba.com/blogs/2026/southeast-asia/apparel-accessories/carton-box-packaging-ect-stacking-moisture-guide-alibaba-b2b)
- Carton drop test is a standard QC-inspection check on full master cartons. It fails if there is significant damage to the carton, inner packs or product — [QC Advisor](https://www.qcadvisor.com/es-mx/wp-json/wp/v2/posts/1795); [Global Sources: Are carton drop tests useless](https://www.globalsources.com/knowledge/are-carton-drop-tests-useless/). Brands often require ISTA packaging tests for apparel — [Eurofins ISTA packaging](https://www.eurofins.com/textile-leather/services/testing-services/ista-packaging/)

### Inferences
- **Packing Instruction doctype (per PO, or per PO × ship-to):**
  - pack type (Solid / Ratio / Mixed)
  - ratio table (colour × size → qty per carton)
  - pcs per polybag (single / blister)
  - fold method, polybag spec, hanger yes/no, tissue yes/no
  - carton spec (from a carton master: L×W×H inside/outside, ply, ECT/burst, tare weight, max gross)
  - max pcs per carton and max gross kg
  - label template (GS1-128 / retailer), marks text
  - ship-to / DC / store, and Canada flag
- **Packing List lines:** carton no. from–to, number of cartons, colour, size breakdown (one column per size), pcs per carton, total pcs, net weight per carton, gross weight per carton, total NW/GW, L×W×H (cm), CBM per carton, total CBM, SSCC range (or per-carton SSCC child table), PO, ship-to.
- **Carton marks:** Main marks are usually on the two long sides: buyer, PO no., style, colour, destination/DC, carton no. "x of y", "Made in Vietnam". Side marks are usually on the short sides: size breakdown, qty, NW/GW, dimensions. Exact content comes from the buyer manual (unsourced practice).
- **SSCC generator:** company prefix plus a serial counter. Never reuse a number, including after reprint or repack. A reprint keeps the same SSCC unless the contents change. If contents change, issue a new SSCC, void the old one and resend or amend the ASN.
- **ASN (856) hierarchy:** Shipment (S) → Order (O, PO) → Tare (T, pallet, optional) → Pack (P, carton SSCC) → Item (I, GTIN/UPC + qty). Standard X12 856 HL structure; "SOTPI" and "SOPI" are common retailer variants. This comes from training knowledge and was not verified from a source in this pass.
- **Weight cap in kg:** 50 lb = 22.68 kg. That is why "23 kg" is often quoted. Enforce the lower of the buyer cap and the carrier cap.

### Gaps
- Walmart, Target, Macy's and Nordstrom routing guides are behind supplier portals and were not retrieved.
- The exact GS1-128 label zone layout (A–I zones: ship-from, ship-to, carrier PRO/BOL, postal code (420), PO (400), store/mark-for (91), SSCC (00)) was not retrieved from a primary source.
- The ISTA test procedure (e.g. ISTA 1A/2A/3A, or 6-Amazon) and the drop heights for apparel cartons were not retrieved.
- No source found for "5-ply" requirements. 3-ply (single wall) versus 5-ply (double wall) choice is buyer- or factory-specific.

## 4. Formulas

### Takeaway
Cartons = ceil(qty ÷ pcs per carton). CBM per carton = L × W × H (in m), and total CBM = CBM per carton × cartons. Gross weight = net weight (garments plus, by convention, inner packing) + carton tare. Air volumetric weight = L × W × H (cm) ÷ 6000. Chargeable weight = max(actual, volumetric). Express couriers often use ÷ 5000.

### Cited Findings
- CBM = L(m) × W(m) × H(m) per carton. Net weight is the goods without packaging; gross weight includes packaging (and pallets) — [apparelandgarmentsbusiness blog](https://apparelandgarmentsbusiness.blogspot.com/2026/05/how-to-create-accurate-packing-lists.html)
- Air: volumetric weight = cm³ ÷ 6000 (IATA). 1 CBM = 166.67 kg volumetric. Chargeable weight = MAX(actual kg, volumetric kg). Some express couriers use 5000 — [CargoAi help](https://help.cargoai.co/a/4535213-what-is-chargeable-weight); [Maersk: air cargo chargeable weight](https://uescpcd.maersk.com/logistics-explained/transportation-and-freight/2025/03/10/air-cargo-chargeable-weight); [iContainers](https://www.icontainers.com/chargeable-weight-vs-actual-weight-air-freight/)

### Inferences
- **Solid pack:** full cartons = floor(Q ÷ P), remainder r = Q mod P, so cartons = ceil(Q ÷ P), and the last carton holds r pieces if r > 0.
- **Ratio pack:** with ratio vector R (sizes s), pack size P = ΣR_s.
  - Number of full prepacks n = min_s floor(Q_s ÷ R_s).
  - Leftover per size L_s = Q_s − n·R_s. Pack the leftovers as solid or mixed "odd" cartons, or round the order to a multiple of the ratio (needs buyer approval).
- **Net weight per carton** = pcs × garment unit weight (+ polybag, tissue and hanger if the buyer counts them as net; conventions vary, so make it a setting). Gross weight = net + carton tare (+ dividers and tape).
- **Validations:** gross ≤ max carton kg; cartons in the packing list × pcs = PO qty per size within allowance; total NW on the packing list = commercial invoice = B/L.
- **Container fill** (rule of thumb, unsourced): a 20' GP holds about 25–28 CBM usable, a 40' GP about 55–58 CBM, a 40' HC about 65–68 CBM. Treat these as configurable.
- **Ocean LCL** is charged per revenue ton, the greater of CBM or tonnes (1 CBM ≈ 1000 kg). This convention was not sourced (see Gaps).

### Gaps
- No primary source found for the ocean LCL W/M (1 CBM = 1000 kg) convention or for usable container CBM.
- No source states whether polybags and hangers count in net weight. Practice varies by buyer.

## 5. Edge cases

### Takeaway
The main edge cases are:
- odd/mixed last cartons
- multiple ship-tos (DCs or stores) per PO, each needing separate cartons, labels and ASN orders
- ratios that don't divide the order quantity
- short or excess shipment within tolerance
- repack after a failed final inspection (new SSCCs, ASN amendments)
- label reprints (same SSCC)
- Canada-specific bilingual labelling
- late buyer-nominated trims

Sources mostly confirm the rules the edge cases rest on (SSCC uniqueness and never reusing it, label/ASN match, Canadian relabelling). The handling procedures are industry practice.

### Cited Findings
- SSCCs can never be reused and must match the electronic documents exactly — [SPS Commerce](https://www.spscommerce.com/community/articles/labeling-for-new-suppliers-gs1-128-sscc-and-where-labels-have-to-go)
- A label without a valid matching 856 cannot be used, so any repack must update the ASN — [Dick's UCC128 requirements](https://edi.jobisez.com/edi-igs/Dicks%20Sporting%20Goods/DICKS_UCC128%20Label%20Requirements.pdf)
- Canada: improperly labelled imports may be relabelled in Canada only after notifying a Competition Bureau inspector at or before import, with goods, quantity, date, port and relabelling address. Fibre content must be bilingual — [Competition Bureau](https://competition-bureau.canada.ca/labelling/textile-labelling/textile-labelling-requirements)
- Ratio depends on destination market and order booking, so different ship-tos may get different ratios — [onlineclothingstudy](https://www.onlineclothingstudy.com/2016/11/different-types-of-garment-packing.html)

### Inferences (proposed ERP rules)
- **Last odd carton:** flag the carton type as "Odd/Mixed". Allow a mixed size breakdown and a smaller carton size from the carton master. Print the actual breakdown on the side mark. Some buyers forbid mixed cartons, or require them to be the last carton number or marked "MIXED", so make this a per-buyer setting.
- **One PO, several ship-tos:** split the PO quantity by ship-to (store/DC allocation, "mark-for"). Generate a Packing Instruction and carton sequence per ship-to, and an ASN either per ship-to or per shipment with separate O levels. Carton numbering restarts per ship-to or continues per PO, depending on the buyer.
- **Non-dividing ratio:** compute n full prepacks plus a leftover per size. Options: (a) leftovers as solid odd cartons, (b) adjust the order to the nearest multiple with buyer approval, (c) ship short within tolerance.
- **Short/excess:** buyer tolerance (e.g. ±3–5% per PO, or per colour/size; not sourced) is configured per buyer. Block packing-list confirmation if a size or PO is outside tolerance, with an override and approval.
- **Repack after failed final inspection (AQL):** void the affected carton SSCCs (status Void, never reused), unpack the pieces back to finishing for rework, repack with new SSCCs and regenerate the packing list version (rev no.) and the ASN.
- **Label reprint:** same SSCC, with a reprint counter and reason logged.
- **Canada:** label BOM variant (bilingual fibre content, CA no.), bilingual carton marks if the buyer requires them, and a CBSA country-of-origin marking check.
- **Late buyer-provided hang tags or price tickets:** allow "packed pending trims" status, i.e. cartons staged but not sealed or labelled. Alternatively, allow packing with trims applied later (requires reopening cartons and a second needle/QC check). Track trim ETA against the ex-factory date in T&A.

### Gaps
- No public source found for standard shipment tolerances (±%) for US brands. These are PO or vendor-agreement terms.
- Retailer rules on mixed or odd cartons (allowed or forbidden, labelling) were not retrieved from routing guides.

## 6. How ERPs model packing (ERPNext and apparel ERPs)

### Takeaway
ERPNext's Packing Slip is a simple, Delivery-Note-bound document: a From/To package number range, item lines, net weight (sum of items) and gross weight. It has no carton master, ratio generator, SSCC, CBM or per-ship-to logic. Apparel packing needs a custom Packing Instruction / Carton / Packing List model on top. EDI vendors (AIMS360, SPS) handle SSCC/GS1-128 and 856.

### Cited Findings
- ERPNext Packing Slip: created from a Delivery Note, only while the Delivery Note is in Draft. Several slips can be made per Delivery Note. Fields include From Package No / To Package No (e.g. 1–5, 6–10), an items table (qty, UOM, net weight and weight UOM fetched from the Delivery Note; batch required for batched items; page break), Net Weight (sum of item weights), Gross Weight (including packing materials) and Gross Weight UOM. Printable on letterhead — [ERPNext docs: Packing Slip](https://docs.frappe.io/erpnext/user/manual/en/packing-slip)
- Apparel ERP vendors offer UCC/GS1-128 label printing integrated with EDI for fashion retailers — [AIMS360](https://www.aims360.com/features-integrations/ucc-128-label-printing-edi-fashion-retailers)
- A Frappe-based garments app documents in-line quality checks (sign of the apparel ecosystem on Frappe) — [garments.l.frappe.cloud docs](https://garments.l.frappe.cloud/docs/quality/inspections/inline-quality-checks)

### Inferences
- **ERPNext gaps for apparel:**
  - no carton master (dimensions, tare, ply, max kg)
  - no ratio/prepack definition
  - no size-breakdown matrix per carton range
  - no CBM
  - no SSCC
  - no ship-to split
  - no link to the buyer packing instruction
  - the Packing Slip only exists from a Draft Delivery Note, which is too late, since factories pack days before invoicing
- **Proposed model:**
  - *Carton Master* (code, inner/outer L×W×H, ply, ECT/burst, tare kg, max gross kg)
  - *Packing Instruction* (PO/ship-to, pack type, ratio child table colour×size→qty, trims, fold, polybag, label template)
  - *Packing List* (generated from Packing Instruction + finished-goods qty; header totals; child Carton Range rows: from, to, count, carton master, size-qty JSON or columns, NW, GW, CBM)
  - *Carton* (one row per physical carton: carton no., SSCC, status Packed / Sealed / Labelled / Loaded / Void, contents child table SKU/GTIN/qty, actual weight, reprint count)
  - optional *Pallet*
  - Link the Packing List → Delivery Note / Shipment and → the 856 ASN export.
  - Generate ERPNext Packing Slips automatically from the Packing List if needed.
- **Generator algorithm:** for each ship-to and colour, compute full ratio cartons, then leftovers, then odd cartons. Assign sequential carton numbers and SSCCs, compute weights from the item unit weight and carton tare, check max kg (if exceeded, reduce pcs per carton or pick a larger or smaller carton), and total up CBM.
- ERPNext also has a Shipment doctype (parcels, pickup/delivery addresses) intended for courier integrations. It is not described in the Packing Slip docs page, so verify its fields before reusing it.

### Gaps
- ERPNext Shipment doctype fields were not retrieved.
- Feature details of commercial apparel ERPs' packing-list generators (e.g. ratio-based auto packing in WFX, BlueCherry, AIMS360) were not retrieved, beyond AIMS360's label/EDI page.
