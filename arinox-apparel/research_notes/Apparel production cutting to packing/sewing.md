# Bulk Sewing in a Woven-Garment Export Factory (Vietnam, US brands): line planning, loading, bundle flow, output tracking, inline quality

Scope note: Most public sources are practitioner sites (mainly onlineclothingstudy.com), slide decks and vendor blogs. I found no ILO/Better Work productivity benchmark and no public buyer quality manual in the time available. Vendor blogs (scan-erp.web.app, garmentbot) sell software, so their numbers are marked as such. Anything not tied to a source is under "Inferences" (my reading of common practice, to be checked with the factory).

## 1. Operation bulletin (OB), SAM, target, line balancing, pitch time, bottleneck

### Takeaway
The OB is the IE document created per style before loading. It lists operations in sequence with SAM, machine type and the planned and allocated manpower/machines. From it come the target per hour (operators × 60 × efficiency ÷ SAM), pitch time and the balance check (each operation within ±10–15% of pitch time). Operations above the band are bottlenecks and get a second operator or machine. Operations well below it are combined.

### Cited Findings
- Before loading a new style, IE prepares an OB. In it, IE plans manpower and machine needs from the SAM of every operation (pitch time) and the production target per hour or per day. The OB shows a calculated (theoretical) machine count and an allocated (practical) count. Example polo shirt: 26.42 calculated vs 29 allocated, because fractional machines cannot be placed. That sample's balancing loss was 9.78%. — [onlineclothingstudy: balancing loss](https://onlineclothingstudy.com/?p=10418) (search snippet; also [2014 version](https://www.onlineclothingstudy.com/2014/11/what-is-balancing-loss-in-garment.html))
- Basic Pitch Time (BPT) = Total basic minutes ÷ total number of operations. Total basic minutes = sum of basic minutes per operation, or SAM × (1 − allowance%). UCL/LCL = BPT ± 10–15% (the standard is ±10%; the article's diagram uses ±15%). Rule: an operation inside UCL–LCL gets 1 machine, and one above UCL gets 2 machines. — [onlineclothingstudy: BPT, UCL, LCL](https://onlineclothingstudy.com/?p=10935)
- Alternative definition from a university text: pitch time = garment SAM ÷ number of operators needed to meet the target. Operations whose combined SAM is at or below pitch time can share one operator or machine (±15% band). — [Vidyamitra/INFLIBNET e-text unit 5](https://vidyamitra.inflibnet.ac.in/data-server/eacharya-documents/56b0853a8ae36ca7bfe81449_INFIEP_79/33/ET/79-33-ET-V1-S1__new_unit_5.pdf) (search snippet)
- Pitch diagram: a bar or line chart of each operation's SAM against the pitch-time line, used to see which operations are over or under. — [onlineclothingstudy: pitch diagram](https://www.onlineclothingstudy.com/2011/11/what-is-pitch-time-pitch-diagram-and.html)
- Traditionally, line balancing is done once at line set-up from historical data. Some factories now collect real-time workstation data to rebalance. — [onlineclothingstudy: 7 things to balance a line](https://onlineclothingstudy.com/?p=10058) (search snippet)
- Daily target = (operators × working hours × 60 × line efficiency%) ÷ product SAM. — [onlineclothingstudy: target in initial days](https://www.onlineclothingstudy.com/2014/03/how-to-calculate-production-target-and.html) (search snippet)
- A vendor blog claims line balancing typically adds 10–20% to line output. This is unverified. — [garmentbot blog](https://garmentbot-ai.pages.dev/blog/apparel-manufacturing-efficiency/) (search snippet)

### Inferences
- OB header fields an ERP needs: style, buyer, product type, OB version/revision, total SAM, target efficiency %, planned operators, working minutes, target/hour, target/day, pitch time, UCL/LCL, balancing loss %, prepared-by and approved-by (IE), and the source of SAM (GSD/PTS, time study, or a library).
- OB line fields: seq no, operation description, garment section (e.g. collar, cuff, sleeve, front, back and assembly for shirts; fly, pockets, waistband, inseam/outseam for pants), machine type (SNLS, DNLS, 3/5-thread overlock, feed-off-the-arm, bartack, buttonhole, button sew, kansai/waistband, blind hem, manual/helper, iron), attachment/folder/guide, SAM, skill grade (often A/B/C), theoretical operators = SAM ÷ pitch time, allocated operators, and remarks (critical operation flag).
- Total SAM = sum of the operation SAMs, including manual and helper operations. SAM already includes allowances (personal, fatigue and delay, often 10–20%). The BPT formula above uses basic minutes, which exclude allowances. The ERP should store both basic time and allowance% per operation so that both pitch-time conventions can be computed.
- Target per hour at 100% = operators × 60 ÷ SAM. Planned target = that × efficiency%. Bottleneck = the operation with the highest SAM ÷ allocated operators, and it caps line output at 60 ÷ (SAM/operators) per hour.
- Balancing loss % ≈ (allocated operators − theoretical operators) ÷ allocated operators. This matches the 26.42 vs 29 example: (29 − 26.42) ÷ 29 = 8.9%. The article's 9.78% may be computed differently, so check this.

### Gaps
- No public source gave a typical SAM range for woven shirts, pants or denim. A specific SAM database (GSD) was not consulted.
- Skill-grade conventions (A/B/C or 1–5) are not standardised in the sources found.

## 2. Line loading / line plan, learning curve, changeover, capacity

### Takeaway
Capacity in minutes = operators × working minutes × efficiency. Orders are loaded onto lines in planned minutes (order qty × SAM), and the first days of a new style follow a learning curve of rising daily efficiency. Changeover can take 15–25% of available time on short runs, and SMED or pre-setting cuts it a lot. I found no authoritative day-wise curve. Each factory builds its own per line and product type.

### Cited Findings
- During the first 1–3 days of a new style (depending on style and production system), line efficiency builds up day by day toward peak. Factories should build their own learning curves per line, style or order. Day-wise planned efficiency is used to set daily targets in the initial days. — [onlineclothingstudy: target & bonus in initial days](https://www.onlineclothingstudy.com/2014/03/how-to-calculate-production-target-and.html) (search snippet)
- Causes of the learning effect: new operation, a different machine or different settings and guides, and different material. The curve is plotted as time per unit or efficiency against cumulative repetitions, at operator level (built at the training stage) or line level. Short-run orders may never reach peak efficiency, so they may need their own curves. Uses: daily targets, day-wise output plans, lead-time estimates and lower incentive thresholds in learning days. — [onlineclothingstudy: learning curve](https://www.onlineclothingstudy.com/what-is-learning-curve-in-apparel)
- Line efficiency also appears as (SAH produced ÷ total hours worked) × 100. — [onlineclothingstudy: SAH hit rate](https://www.onlineclothingstudy.com/2020/01/what-is-sah-hit-rate.html) (search snippet)
- One paper on a digital changeover platform (SMED) reports average changeover time falling about 40–50% across style changes on two lines. A case study cut sewing changeover from more than 30 minutes to less than 10. — [onlineclothingstudy: StitchGrid / SMED](https://www.onlineclothingstudy.com/2025/08/stitchgrid-digitally-optimizing-changeover.html) (search snippet)
- A vendor blog estimates changeover takes 15–25% of available time on short runs. It suggests efficiency targets above 70% generally and above 80% for experienced lines on familiar styles. These figures are unverified. — [garmentbot blog](https://garmentbot-ai.pages.dev/blog/apparel-manufacturing-efficiency/) (search snippet)
- Short-run orders need specific tactics to reach high efficiency. — [onlineclothingstudy: shorter run orders](https://www.onlineclothingstudy.com/2018/03/how-to-get-maximum-efficiency-in.html) (title only, not read)

### Inferences
- Line plan record: line, style/PO/colour, planned qty, SAM, planned operators, start date, end date, day-wise planned efficiency (learning curve array, e.g. a curve table keyed by product type and "new vs repeat style"), changeover minutes, day-wise target qty. The planned end date is reached when the cumulative target is at least the order qty.
- Daily capacity (minutes) = present operators × shift minutes (plus overtime minutes) × planned efficiency. Required minutes = qty × SAM. Load % = required ÷ available.
- In practice the day-wise learning curve varies widely: day 1 often runs at 30–50% of the target efficiency, reaching the steady state in about 3–7 days for complex woven items. These are practitioner figures and could not be sourced. The ERP should make this a configurable table, not a hard-coded rule.
- Repeat styles or "carry-over" lines should get a shorter curve. A line running a similar style before (shirt to shirt) should get a shorter curve than a product change (shirt to pant).

### Gaps
- No public, sourced day-wise learning-curve percentages were found. The onlineclothingstudy curve is an image.
- No ILO/Better Work line-efficiency benchmark for Vietnam was found. Better Work and ILO factory reports would be the next place to look.

## 3. Bundle flow: cutting → sewing input, WIP, bundle tickets/scanning, PBS vs UPS vs modular

### Takeaway
Cut panels are bundled with a ticket encoding style, cut no, size, shade or ply range, and quantity, and are issued to a line ("input"). Sewing WIP per line = pieces loaded − pieces output. Barcode or RFID bundle tickets allow scanning per operation, which gives operator efficiency and piece-rate data. PBS (bundles) is the most common system. UPS (overhead hangers) and modular or team systems run lower WIP, but the evidence on their benefits is mixed.

### Cited Findings
- Each bundle gets a ticket number representing style, size, shade and number of cut pieces. — [Apparel merchandising learner: cut piece preparation](https://apparelmerchandisinglearner.blogspot.com/2019/11/cut-piece-preparation-for-sewing.html) (search snippet)
- RFID- and barcode-based shop-floor tracking systems both use a bundle card or barcode sticker attached to the bundle. When the tickets are scanned, the system generates individual operator efficiency. Bundle tickets also support individual performance bonuses. — [onlineclothingstudy: bundle tickets & bonus](https://www.onlineclothingstudy.com/2012/09/bundle-tickets-individual-performance.html) (search snippet)
- WIP formulas: Cutting WIP = total cut qty − total qty sent to sewing. Sewing WIP = qty loaded to line − qty output from line. Example: 3,000 loaded and 2,500 out gives 500 WIP. — [onlineclothingstudy: WIP levels](https://www.onlineclothingstudy.com/2012/10/how-to-calculate-wip-level-in-cutting.html) (search snippet)
- After line balancing, cut panels go into the line bundle by bundle to workers in a set sequence. — [SlideShare: sewing department](https://www.slideshare.net/slideshow/sewing-department/201414511) (search snippet)
- ERP practice: auto-generated unique bundle numbers and printed barcode stickers per bundle. — [Logic ERP KB: bundle movement](https://kb.logicerp.com/logic-erp-in-action-a-feature-overview/manufacturing/batch-lot-bundle-movement-process-flows) (search snippet)
- Vendor view: the cutting-to-sewing hand-off fails most often. Bundles leaving cutting without a label become "ghost inventory" that is sewn but never counted. — [scan-erp vendor blog](https://scan-erp.web.app/blog/cutting-room-to-sewing-floor-bundle-tracking.html) (vendor, search snippet)
- PBS is described as the most widely installed sewing system. Operators tend to sew as many pieces as they can, regardless of the stations before and after them, so work piles up at slow stations. In UPS, an overhead hanger moves all the components of one garment, and each station holds hangers up to a set limit, which caps WIP. One comparison claims PBS needs more cutting ahead and more fabric and trim stock. — [onlineclothingstudy: PBS vs UPS](https://onlineclothingstudy.com/?p=11216) (search snippet)
- Counter-view: Apparel Resources argues that UPS itself does not reduce WIP, and across a full line it can lengthen throughput. It credits the WIP reduction to the overhead hangers, not the unit concept. — [Apparel Resources: knowledge divide – UPS](https://apparelresources.com/technology-news/manufacturing-tech/the-great-knowledge-divide-iv-unit-production-system/) (search snippet)
- A comparative study of Bangladeshi factories found UPS outperformed PBS, but the results varied by factory and style. — [IEOM Society paper](https://index.ieomsociety.org/index.cfm/item/53908) (search snippet)

### Inferences
- Bundle ticket fields: bundle no (unique barcode), PO/style, colour, size, cut no / lay no, shade code or roll no, ply range (e.g. plies 21–40), qty, and component list or sub-bundles (e.g. collar, cuff, front, back for a shirt). For pants and denim, front and back panels often have separate tickets per component. Each ticket gets tear-off coupons per operation where piece-rate pay is used. Vietnamese export factories increasingly use barcode/QR or RFID with hanger systems, but the share could not be sourced.
- Bundle size is usually 10–30 pieces for woven bulk. It is smaller for UPS and modular and is set at cutting. This is practitioner knowledge, not sourced.
- Line input document: "Sewing Input / Cutting Issue" header (date, line, PO/style/colour) with bundle rows. It moves qty from cutting WIP to line WIP. Line WIP in pieces ÷ hourly target = WIP hours, a common control (often 1–3 hours of WIP for PBS, unsourced).
- Scan points to support: line input, optional per-operation scans (for piece rate or operator efficiency), end-line QC pass/defect, and line output to finishing or wash.

### Gaps
- No source gave standard bundle sizes or WIP-hour targets.
- No 2018–2026 data on how many Vietnamese factories use PBS, UPS (e.g. Eton) or modular systems was found.

## 4. Output tracking: hourly production, daily output, efficiency, DHU, defect %, RFT

### Takeaway
Track hourly output per line (pieces passed at end-line), compute line efficiency = (output × SAM) ÷ (operators × minutes worked) × 100, and record quality as DHU (defects ÷ pieces checked × 100), defect % (defective pieces ÷ checked × 100) and RFT (pieces passing first time ÷ total × 100). Reworked pieces count as output once they pass, but never toward RFT.

### Cited Findings
- RFT% = first-time passed units × 100 ÷ total production units. Example: 380 of 400 is 95%. Repaired garments are not first-time passes, so a lot's pass % is not RFT. — [onlineclothingstudy: RFT](https://www.onlineclothingstudy.com/2019/08/what-is-right-first-time-quality-in.html)
- Worked example: 450 inspected, 50 repaired or rejected, gives RFT 88.89% and defect % = 100 − RFT = 11.1%. — [Apparel Resources: quality measurement tools](https://apparelresources.com/business-news/manufacturing/improve-quality-levels-using-measurement-tools/) (search snippet)
- DHU = total defects found × 100 ÷ total pieces checked. One garment can have several defects, and each is counted because each adds rework. — [Apparel Resources: quality measurement tools](https://apparelresources.com/business-news/manufacturing/improve-quality-levels-using-measurement-tools/) (search snippet)
- Defect % is defective units per 100 garments checked, distinct from DHU. — [onlineclothingstudy: RFT](https://www.onlineclothingstudy.com/2019/08/what-is-right-first-time-quality-in.html)
- Vendor blog claim: on a new style, DHU runs 3–5× steady state on day 1 and 2–3× in week 1. This is unverified. — [scan-erp vendor blog: DHU benchmarks](https://scan-erp.web.app/blog/dhu-benchmarks-garment-factory-2026.html) (vendor, search snippet)
- Line efficiency = SAH produced ÷ hours worked × 100. — [onlineclothingstudy: SAH hit rate](https://www.onlineclothingstudy.com/2020/01/what-is-sah-hit-rate.html) (search snippet)

### Inferences
- Hourly production report (HPR) grid: line × hour slot (e.g. 07:30–08:30 … plus OT hours), with target, actual output, cumulative, variance and reason code (machine breakdown, feeding shortage, absenteeism, quality stop, style changeover). Efficiency for the hour = output × SAM ÷ (operators present × 60) × 100.
- Operators in the denominator: decide whether helpers, ironers and line-side QC are included, and whether the minutes are attendance minutes or "on-standard" minutes (with off-standard or NPT such as no-feeding or breakdown deducted). Factories differ. Make it configurable and store both "line efficiency" and "on-standard efficiency".
- Daily output: by PO/style/colour/size, from end-line pass scans or tallies. It feeds order progress (cut, input, output, washed, finished, packed).
- Rework pieces: when a repaired piece passes re-check, it is added to output (good pieces). It is excluded from RFT, and its defects still count in DHU. Rejected pieces (beyond repair) leave the line as "reject" and reduce the order balance unless replaced.

### Gaps
- No authoritative DHU or RFT targets for US-brand woven programs were found. Brand manuals (e.g. PVH, Levi's, Gap) are not public.
- No public standard hourly-report template was found.

## 5. Inline inspection (traffic light), end-line audit, defect categories, rework, rejects / panel replacement

### Takeaway
Under the Traffic Light System (TLS), a roving inline checker samples 5 or 7 pieces per operator per round (commonly every ~2 hours) and colour-codes the operator green, yellow or red. Thresholds vary by factory. Under the stricter "7.0" variant, any defect in 7 pieces means red. The end-line checker inspects 100% of output, logging pass/defect by hour and defect type. Repairs go back to the operator and are re-checked. Damaged panels are replaced by re-cutting from the same roll or shade.

### Cited Findings
- Normally 5 or 7 garments are checked per operator by the quality checker. One version gives yellow for 1 defect and red for 2. — [onlineclothingstudy: TLS for quality](https://onlineclothingstudy.com/2012/01/traffic-light-system-for-quality.html) (search snippet)
- The 7-piece sample comes from J.C. Penney's supplier format. It was reduced because auditors often did not find 7 pieces at a station in low-WIP systems. A 7-piece-era rule gave a red card for 5 or more defective out of 7. — [fibre2fashion: TLS visual QC tool](https://fibre2fashion.com/industry-article/6990/traffic-light-system-a-visual-quality-control-tool) (search snippet)
- "7.0 system": 7 pieces checked, and a single defective garment means RED. — [onlineclothingstudy: 7.0 system](https://onlineclothingstudy.com/what-is-70-system-in-garment-inspection/) (search snippet)
- One factory-based document lists a standard sample size of 5 pieces, and inspection rounds are commonly every two hours. — [apparelsclassroom: TLS](https://apparelsclassroom.blogspot.com/2018/05/traffic-light-system-for-ensure-quality.html) (search snippet)
- TLS colour meanings: Green means few or no defects and production continues. Yellow means moderate defects, so the operator is monitored and guided and minor machine adjustments may be needed. Red means a high defect rate: production may stop, immediate correction is needed, and retraining or mechanic support may follow. Checks are at regular intervals, in sequence or random. — [onlineclothingstudy: TLS (2026)](https://www.onlineclothingstudy.com/2026/05/what-is-tls-in-garment-industry.html)
- Trouser defect list (seams and stitching): twisted, roped or puckered seams; open or broken stitches; raw edges; missing back tacks or bar tacks; uneven topstitch; seam grin or slippage; caught material; SPI out of spec; wrong stitch type; missing double-needle crotch seam. Buttonholes: out of size, frayed, not cut, misplaced. Buttons: insecure, missing, broken, misaligned. Waistband: uneven width, twist, misaligned closure. Belt loops: insecure, above waistband, missing tacks, thread shade off. Pockets: uneven, misaligned, missing bartack or rivet, puckers. Zipper: malfunction, wavy, uneven stitching, missing bottom bartack. Fly: uneven width, zipper top not caught in band, one side overextended. Hems: twisted, uneven. Labels: wrong text or position, insecure. Plus fabric (holes, slubs, shade variation, bow/skew > 1.5%), cleanliness (stains, loose threads) and pressing defects. — [onlineclothingstudy: trouser defects](https://onlineclothingstudy.com/?p=11124)
- Stitch-defect definitions: skipped stitch, puckering (may show only after laundering, linked to thread tension), broken stitch, open seam. — [onlineclothingstudy: stitching defects](https://www.onlineclothingstudy.com/2016/10/stitching-defects-found-in-knits.html); [general list](https://www.onlineclothingstudy.com/2011/10/list-of-defects-found-in-garments.html)
- Panel replacement SOP: re-cut from the same roll or shade using a mini-marker. If the roll is finished, use the same dye lot or shade with cutting QC or management approval. Use the approved hard pattern and exact grain. QC confirms the new panel 100% matches the other panels of the same cut number. — [Garments-Info: cut panel replacement SOP](https://garments-information.blogspot.com/2019/04/cut-panel-replacement-sop-standard-operating-procedure.html) (search snippet)
- Replacement fabric can come from end bits of the lay, fresh fabric, or good parts of another garment. Fresh fabric risks shade mismatch, while solids and yarn-dyed fabric are lower risk. For heavily washed garments, shade matching is very hard, and the garment may need re-washing after a part is changed. — [onlineclothingstudy: changing damaged parts](https://onlineclothingstudy.com/2011/06/how-to-change-defective-or-damaged.html) (search snippet)

### Inferences
- Inline (TLS) record: date, line, round no (e.g. 4–5 rounds/day), operator, operation, pieces checked (5 or 7), defects found by code, colour result, action taken, re-check result. A rule engine can compute the colour from a configurable threshold table (e.g. Green 0, Yellow 1, Red 2 or more; or the 7.0 rule where 1 or more means Red). Consecutive reds trigger escalation (stop the operation, call a mechanic or supervisor).
- End-line QC record: hourly grid of checked, passed, defective pieces, and defects by code and position (body area). Pieces go to rework with a ticket, and the rework-returned qty is logged as "re-checked pass" or "reject". This gives DHU, defect % and RFT per hour, per line and per operation responsible.
- Woven shirt defect codes (practitioner standard, not sourced here): collar point uneven or shape off, collar or band puckering, top-stitch uneven, cuff shape uneven, placket twisted or uneven, sleeve placket wrong, stripe or check mismatch (critical for yarn-dyed shirts), button or buttonhole misaligned, label missing or wrong position, shade variation between panels, side-seam puckering, hem roping, measurement out of tolerance.
- Rework vs reject: rework is repairable on the line (unpick and resew) and counts as output after it passes. A reject is a damaged panel (needle hole, cut, stain that won't clean, shade off) that cannot be repaired. Either the garment is held for panel replacement (a "panel replacement request" to cutting citing bundle and ply number, so that shade and ply match), or it is written off as a B-grade or reject garment against the cut-to-ship reconciliation.

### Gaps
- No public US-brand inline or end-line standard (e.g. sample per round, rounds per day) was found. Brand QA manuals are typically confidential.
- No source gave typical end-line DHU or reject rates for woven shirts or denim.

## 6. Sewing trims issue (thread, labels, buttons) against the trim card

### Takeaway
Sewing trims are issued from the trims store against a sewing department requisition based on the BOM or consumption (thread per garment plus wastage). The line QC or supervisor checks them against the approved trim card before use. Pre-bulk trims averages are recalculated before bulk to avoid shortages.

### Cited Findings
- Cutting raises fabric requisitions and sewing raises trims requisitions. The warehouse checks consumption. — [SlideShare: garment industry overview dept-wise](https://es.slideshare.net/negatve/an-overview-in-garment-industry-dept-wise) (search snippet)
- The store issues trims per the BOM and records incoming and outgoing. Received trims are checked by the line quality supervisor before use and returned to the store if they fail. — [SlideShare: apparel manufacturing process](https://www.slideshare.net/slideshow/apparelmanufacturingprocess-140214034521phpapp01-101870700/101870700) (search snippet)
- SOP: calculate the bulk average for all trims consumed in production (thread, elastic, tape, zipper, lace, lining, fusing) before bulk. Collect the trim sheet (card) from the trims store to avoid quality mismatches on a running order. — [onlineclothingstudy: SOP trims average](https://onlineclothingstudy.com/sop-for-calculating-initial-trims/)
- Thread consumption = the length of thread per garment for a style, plus a wastage %. It is used to plan purchases and to reduce wastage and shortages. — [onlineclothingstudy: thread consumption](https://onlineclothingstudy.com/?p=8419) (search snippet)

### Inferences
- Trims issue document: line, PO/style/colour, input qty (cut qty issued to the line), and per item: BOM qty per garment, allowance %, qty issued, issued to date, balance. Over-issue needs approval. Thread is issued in cones (consumption per garment ÷ metres per cone, by colour and ticket number). Labels (main, size, care/content, country of origin) are issued by size and controlled as counted items, because size and care labels are audited by US brands. Buttons are issued by count plus a small allowance.
- Trim-card check: line-side verification that the issued item matches the approved trim card (colour, size, code, supplier) before the first piece. Record it as a checkbox or signature on the line set-up checklist.
- Returns: leftover trims returned to the store at style close, which feeds trims reconciliation.

### Gaps
- No source specified the standard allowance % for sewing trims (practice often 2–5%, unverified).

## 7. Hand-offs: sewing → washing (denim/washed garments) and sewing → finishing

### Takeaway
Sewn garments leave the line against a delivery or transfer document (a challan or gate pass for an outside wash plant) carrying style, colour, buyer and qty, kept shade- and lot-wise. Washing returns qty shade-wise to finishing, and the send/receive qtys are reconciled per style.

### Cited Findings
- Sewn denim is bundled shade-wise and sent to washing. After washing, it is received in finishing in shade-wise bundles. — [SlideShare: garment industry overview](https://es.slideshare.net/negatve/an-overview-in-garment-industry-dept-wise) (search snippet)
- A challan generally contains style no, colour, buyer's name, qty issued and the production unit. — [Scribd/issuu garment working process](https://issuu.com/anilaggarwal1/docs/garment-industry-working-process) (search snippet; source attribution uncertain)
- Washing SOP: keep style and cut lots separate when receiving from sewing, and record the wash formula. — [Scribd: washing SOP](https://www.scribd.com/document/323948462/SOP-RTP) (search snippet)
- Wash-load management matters so that washing is done shade-wise. — [Eurofins: denim stitching & washing](https://www.eurofins.com/assurance/resources/articles/enhancing-denim-quality-best-practices-for-denim-stitching-and-washing/) (search snippet)
- ERPNext/Frappe forum: a wash-vendor outward/inward challan reconciliation on one page (inward on the left, outward on the right). — [Frappe forum: garment processing](https://discuss.frappe.io/t/garment-processing/3045) (search snippet)
- Finishing SOP: submit a style reconciliation report when each style is completed. — [Scribd: finishing SOP](https://www.scribd.com/document/905772998/Finishing-Sop) (search snippet)

### Inferences
- Sewing output to finishing (in-house): "Sewing Output / Line Output Transfer" by PO/colour/size, which moves qty from line WIP to finishing WIP.
- Sewing to washing: "Send to Wash" (delivery note or gate pass), header with wash plant (internal or subcontract), wash recipe or standard reference, and lines by PO/colour/size/cut lot/shade. Then "Receive from Wash" with qty received, wash rejects (holes, damaged), shortages, and shade grouping after wash. Reconcile sent = received + wash rejects + in-process. For denim, the garment usually goes through dry processes (whiskers, hand sand), wash, then back for finishing operations (buttons/rivets, sometimes hemming) after wash. Some sewing operations happen after wash, so the OB or routing must allow post-wash operations.
- Vietnam context: wash plants are often separate legal entities, so the transfer may need a delivery note or subcontract delivery, plus customs implications in bonded or EPE factories. This is unverified and should be checked with the client.

### Gaps
- No standard sewing-to-finishing transfer form was found publicly.

## 8. Edge cases

### Takeaway
The sources say little about edge cases directly. The ERP has to handle them through the data model: everything keyed by line + PO/style/colour/size + cut/bundle (shade), with separate quantity buckets (input, output, rework, reject, replaced) and attendance/downtime records.

### Cited Findings
- Bundle tickets encode shade. Re-cut panels must match the shade of the same cut number, and washed-garment shade matching is hard. — [Apparel merchandising learner](https://apparelmerchandisinglearner.blogspot.com/2019/11/cut-piece-preparation-for-sewing.html); [Garments-Info panel replacement SOP](https://garments-information.blogspot.com/2019/04/cut-panel-replacement-sop-standard-operating-procedure.html) (search snippets)
- Short runs may never reach peak efficiency, so they need separate learning curves. — [onlineclothingstudy: learning curve](https://www.onlineclothingstudy.com/what-is-learning-curve-in-apparel)
- Washed garments: style and cut lots are kept separate, and washing is done shade-wise. — [Scribd washing SOP](https://www.scribd.com/document/323948462/SOP-RTP); [Eurofins](https://www.eurofins.com/assurance/resources/articles/enhancing-denim-quality-best-practices-for-denim-stitching-and-washing/) (search snippets)
- Vendor claim: unlabelled bundles are sewn but never counted. — [scan-erp vendor blog](https://scan-erp.web.app/blog/cutting-room-to-sewing-floor-bundle-tracking.html)

### Inferences (design suggestions, unsourced)
- **Line running two styles** (tail of style A plus start of B): allow multiple active line-plan rows per line per day. Split operators or minutes between styles for efficiency (earned minutes = Σ output_i × SAM_i, so the line efficiency formula still works).
- **Order split across lines or factories:** the line plan sits at PO-colour(-size) qty per line. Output and WIP are aggregated per order across lines. Each line can have its own OB version (different machine set).
- **CMT subcontract of sewing:** issue cut bundles plus trims to the subcontractor on a delivery document (subcontract order). Receive sewn qty back, track subcontractor WIP = issued − received − rejects, and reconcile trims. Their output counts toward order progress but not toward the factory's line efficiency. Inline QC is by a factory QA visiting the subcontractor.
- **Output by colour/size:** bundles are single colour and size, so output by bundle scan rolls up automatically. Manual tallies need a colour × size matrix.
- **Missing panels:** a bundle short of components (e.g. 19 backs for 20 fronts) is noted at input check. Raise a panel shortage or re-cut request against the cut and bundle. The line input qty is the matched-set qty.
- **Shade mix within a bundle:** treat it as a quality hold at input. Re-sort by ply or shade, or replace panels from the same shade group. Garments are never mixed across shades within an order/size/carton.
- **Rework vs reject:** separate quantity fields and defect codes. A reject triggers panel replacement (back to cutting) or a write-off to B-grade, and it affects the cut-to-ship ratio.
- **Absenteeism and overtime:** daily line attendance (planned vs present operators, borrowed or lent operators between lines, OT minutes per operator) drives the efficiency denominator and the replanned target.
- **Line stops / downtime:** a downtime log (start, end, reason: machine breakdown, no feeding/WIP, trims shortage, quality stop (red TLS), power, style changeover, meeting). It is deducted for on-standard efficiency and kept for lost-minute analysis.

### Gaps
- No published standard for CMT subcontract sewing documentation in Vietnam was found.
- Treatment of borrowed operators and helpers in the efficiency denominator is not standardised in the sources.
