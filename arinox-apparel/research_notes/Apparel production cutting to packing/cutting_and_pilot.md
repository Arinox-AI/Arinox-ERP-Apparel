# Start of Bulk Production in a Woven Export Factory: Cutting Order, Pilot Run, Bulk Cutting

Context: a Vietnamese export factory making woven shirts, pants and denim for US brands, with washing done by a subcontractor. Most public sources are practitioner blogs (onlineclothingstudy, Apparel Resources), factory SOPs and CAD vendor help pages, not formal standards. Exact numbers (extra cut %, pilot quantity, bundle size) differ by factory and buyer, so the ERP should hold them as configurable parameters, not hard-coded values. "Cited Findings" sections contain only what the sources say. "Inferences" sections hold design recommendations and general practitioner knowledge that I could not tie to a source; they are marked as such.

## Production card / cutting order: fields, who issues and signs it, how cut quantity is computed

### Takeaway
The cutting order (also called a work order, cut plan or order sheet) turns PO quantity by colour and size into a cut quantity. The formula is cut qty = order qty × (1 + extra cut %), and the extra is commonly 2–5 %. The merchandiser or another authorised person plans that percentage. It rises with fabric risk and with the number of processes the garment goes through, and garment washing is one of the biggest of those.

### Cited Findings
- Formula: cutting quantity = order quantity × (1 + extra cutting %). Cut-to-ship ratio = cutting quantity ÷ shipped quantity. Example: a 10,000-piece order with 2 % extra gives 10,200 cut, and if 10,000 ship, cut:ship = 1.02 — [onlineclothingstudy, Cut to Ship Ratio](https://onlineclothingstudy.com/2013/10/what-is-cut-to-ship-ratio-in-apparel.html)
- "Garment exporters generally cut 2-5% extra garment than order quantity." The percentage "varies depending on fabric types and number of processes involved in conversion" — [onlineclothingstudy](https://onlineclothingstudy.com/2013/10/what-is-cut-to-ship-ratio-in-apparel.html). This 2–5 % range comes from one trade blog. I found no authoritative standard.
- Who sets it: "Extra percentage of cut quantity is planned by merchandiser or other authorised person." — [onlineclothingstudy](https://onlineclothingstudy.com/2013/10/what-is-cut-to-ship-ratio-in-apparel.html)
- Data sources for the ratio: order qty comes from the buyer PO, cut qty from cutting and production reports, and shipped qty from shipping and merchandising — [onlineclothingstudy](https://onlineclothingstudy.com/2013/10/what-is-cut-to-ship-ratio-in-apparel.html)
- Reasons to cut extra: to cover damage and rejects, because some buyers accept overage up to a set % at the same FOB price, and to use up all the fabric sourced. Extra cutting adds fabric, trim and labour cost. The ratio is also used as a KPI for factory and general managers — [onlineclothingstudy](https://onlineclothingstudy.com/2013/10/what-is-cut-to-ship-ratio-in-apparel.html)
- The same site also argues for cutting less extra on sustainability grounds — [onlineclothingstudy, Stop Extra Cutting](https://onlineclothingstudy.com/?p=8839) (opinion piece)
- Fabric allowance is built in separately when fabric is bought, as an overall wastage %, and that allowance is "highly variable" — [Apparel Resources, Fabric management](https://apparelresources.com/business-news/manufacturing/fabric-management-saving-fabric-or-just-increasing-dead-stock/)
- Commercial shipment tolerances are set in contracts, not by industry norms. Sample clauses: ±5 % with pro-rata payment, a 95–110 % acceptance window, or ±10 % for custom goods — [LawInsider, Quantity Tolerance clauses](https://www.lawinsider.com/clause/quantity-tolerance). These are templates, not US brand terms.
- The cutting process starts with "receive the cut plan and marker plan based on the work order", then "prepare the cut ratio". Fabric approval status (quality and shade band) must be verified before spreading — [onlineclothingstudy, Cutting process](https://www.onlineclothingstudy.com/2019/12/cutting-process-in-garment-industry.html)
- Before bulk cutting, consumption must be recalculated from the production marker and compared with the sampling (costed) consumption. If it is higher, the factory may run short and produce less than the order qty, so any variation must be approved — [onlineclothingstudy, 6 checklists before bulk cutting](https://www.onlineclothingstudy.com/2015/04/6-things-to-be-considered-prior-to-bulk.html)
- Fabric requirement should be calculated from lay consumption, not marked consumption — [Apparel Resources, Cut order planning](https://apparelresources.com/business-news/manufacturing/fabric-utilization-i-cut-order-planning/)

### Inferences
- (Design, not sourced) The cutting order header should carry: style, buyer, PO(s), ship-to / destination, delivery date, PCD (planned cut date), fabric reference(s) per component (shell / lining / pocketing / interlining), costed consumption per fabric, approved marker consumption, extra cut %, and approval stamps. These are the PPM sign-off, pilot approval, fabric shade band approval and pattern approval.
- The cutting order should have a matrix of colour × size × destination with these columns: order qty, extra %, planned cut qty, and later actual cut qty.
- Required fabric = planned cut qty × lay (marker) consumption per garment ÷ (1 − end-loss/remnant allowance), per fabric type. The inputs should be stored so the calculation can be audited.
- (Practitioner knowledge, unsourced) Extra cut is often tiered by order size, with a higher % for small orders and a lower % for large ones. Washed or garment-dyed styles usually get a higher % than non-washed ones, because wash damage and shade or shrink rejects add up. I found no public source giving actual tier values. Make it a configurable table (qty band × product type × wash flag → %), with merchandiser override and a reason code.
- Rounding: compute the extra per size and round up, or the per-size totals will not match the total. Many factories apply the extra only to the main sizes or to colours with known risk. Allow per-cell override.
- Signatories (common practice, not sourced): the merchandiser prepares the order, and the production manager or factory manager and the cutting in-charge sign it. Fabric store and QA confirm fabric readiness.

### Gaps
- I found no public buyer manual (Target, Walmart, Gap, PVH, Levi's) that sets extra-cut or overship % for US programmes. Overship and undership tolerance is usually in the buyer's PO terms or vendor agreement, which are not public.
- I found no published tolerance bands by quantity for extra cut.
- I found no standard field list for a "production card" from an apparel ERP vendor (WFX, BlueCherry, etc.), because their docs are not public. I could not reach the GarmentFlow Frappe docs page (HTTP 500).

## Pilot run (pre-production line run): timing, quantity, checks, approval, failure, counting

### Takeaway
The pilot run happens after the PP sample is approved and the PPM is held, and before bulk cutting (PCD). It uses all sizes and colours, or jump sizes, and runs on the real production line. Reported quantities range from 25–30 pieces minimum up to 100–200 pieces per style. Small orders (one factory's cutoff was under 1,000 pcs) often skip it. Bulk cutting is released only when pilot garments measure within tolerance after processing, which for denim means after washing. Pilot pieces that conform ship with the order.

### Cited Findings
- "A pilot run is done after approval of the PP sample and before bulk cutting." The factory loads bulk right after it — [onlineclothingstudy, Pilot run](https://www.onlineclothingstudy.com/2015/04/what-is-pilot-run-in-garment.html)
- The pilot is done when the buyer requests it, or always if the factory has made it standard — [onlineclothingstudy](https://www.onlineclothingstudy.com/2015/04/what-is-pilot-run-in-garment.html)
- Quantity: 100–200 garments per style, with all sizes and colours, though jump sizes may be cut instead — [onlineclothingstudy](https://www.onlineclothingstudy.com/2015/04/what-is-pilot-run-in-garment.html). Other sources say a minimum of 25–30 pcs, cut across all sizes and colours — [Quality control manual (MLSU)](https://mlsu.ac.in/econtents/5880_MVoc_Semester%201_Quality%20Control%20manual_013.pdf); [CSJMU QC manual unit 4](https://gyansanchay.csjmu.ac.in/wp-content/uploads/2022/08/What-is-a-quality-control-manual-for-garments-UNIT-4.pdf). The sources conflict, so the quantity should be configurable.
- Small orders: "Normally garment manufacturers don't perform pilot run for small orders." The author's factory piloted only orders over 1,000 pcs — [onlineclothingstudy](https://www.onlineclothingstudy.com/2015/04/what-is-pilot-run-in-garment.html). A QC manual also says no pilot is required for order qty under 1,000 — [MLSU QC manual](https://mlsu.ac.in/econtents/5880_MVoc_Semester%201_Quality%20Control%20manual_013.pdf)
- The pilot runs on the production line, not in the sampling room. The full planned process is followed, the line is set as for bulk, and the work is based on PP sample comments — [onlineclothingstudy](https://www.onlineclothingstudy.com/2015/04/what-is-pilot-run-in-garment.html)
- Checks: production techniques and quality requirements, with factory QA inspecting at every stage and buyer QA if requested. It also identifies critical and bottleneck operations, cross-checks fabric and thread estimates, re-plans extra processes, and keeps WIP low — [onlineclothingstudy](https://www.onlineclothingstudy.com/2015/04/what-is-pilot-run-in-garment.html)
- Approval criterion: "If the factory gets the right measurement in the pilot run piece after processing, bulk cutting is approved." — [QC manual](https://mlsu.ac.in/econtents/5880_MVoc_Semester%201_Quality%20Control%20manual_013.pdf). Pilot approval "with report" is one of six pre-bulk-cutting checks, and the pilot results must be reviewed for cutting-related points — [onlineclothingstudy, 6 checklists](https://www.onlineclothingstudy.com/2015/04/6-things-to-be-considered-prior-to-bulk.html)
- Counting: pilot pieces ship with the bulk order if they show no variation from the buyer's quality spec — [onlineclothingstudy](https://www.onlineclothingstudy.com/2015/04/what-is-pilot-run-in-garment.html)
- PPM timing: the PPM is held after the PP sample is approved and sealed. The agenda covers the style file checklist, the T&A plan, and PP sample comments. Minutes go to each floor section — [QC manual](https://mlsu.ac.in/econtents/5880_MVoc_Semester%201_Quality%20Control%20manual_013.pdf); [appareltutorial PPM procedure](https://appareltutorial.blogspot.com/2017/08/pre-production-meeting-procedure.html)
- Related records: the size set measurement and inspection report, PPM notes, pilot run / inline comments, and the approved measurement and graded spec — [QC manual](https://mlsu.ac.in/econtents/5880_MVoc_Semester%201_Quality%20Control%20manual_013.pdf)
- Prerequisites for bulk cutting: an approved and sealed production pattern (with shrinkage allowance added by the pattern master), approved marker consumption, approved fabric quality (shade bands, GSM, shrinkage %, width, FPT report), an approved marker plan, pilot approval, and the pre-shrink and relaxation decision with lay rest time — [onlineclothingstudy, 6 checklists](https://www.onlineclothingstudy.com/2015/04/6-things-to-be-considered-prior-to-bulk.html)
- Denim: test shrinkage before bulk cutting (typical acceptable range for standard denim is 2–4 %). Keep an approved swatch and an approved washed sample as the reference — [lydenim](https://lydenim.com/?p=5683) (supplier blog)

### Inferences
- (Design) Sequence of gates in the ERP: PP sample approved → PPM held (minutes logged) → pilot cutting order (a small cut order flagged "pilot", drawn from the bulk fabric rolls) → pilot sewing, then wash at the subcontractor, then finish → pilot report (measurements after wash vs spec, construction, wash look vs approved wash standard, trims, SAM / line balance observations, fabric consumption check) → approval → release of bulk cutting order(s). The bulk cutting order should be blocked until pilot approval is recorded, or until a waiver is recorded for orders under the configured threshold or when the buyer does not require a pilot.
- For washed styles, the pilot round trip to the wash subcontractor is often what limits PCD. The pilot T&A should include wash lead time.
- (Design) Pilot qty should count against the order. Conforming pilot pieces are posted to the colour/size cells they came from. Rejected pilot pieces are written off against the extra-cut allowance. The pilot cut must use real bulk shade lots.
- On failure (not sourced; common practice): correct the pattern or marker (for example, revise the shrinkage allowance after wash), fix the method or line setting, and re-pilot or run a "second pilot" on a reduced quantity. Bulk cutting stays on hold. The ERP needs a pilot status of Pass / Pass with comments / Fail, a reason, and a link to a revised pattern version.
- The approver is not named in the sources. Common practice is that the factory QA head and the production manager approve, plus buyer QA or a third-party inspector when the buyer requires it. This should be configurable.

### Gaps
- No public source gives SAM validation criteria for pilot runs (for example, target vs achieved efficiency).
- No source states what share of a pilot must pass, or a formal fail procedure.
- No public US buyer manual specifying pilot quantity was found.

## Bulk cutting: marker, cut order plan, spreading, shade and roll allocation, lay report, bundling, inspection, re-cut, fusing, reconciliation, KPIs

### Takeaway
Bulk cutting is a controlled chain. Rolls are inspected and grouped by shade, shrinkage and width. A cut order plan (lay plan) sets the marker size ratios and ply counts for each lay. Spreading follows the face and nap rules, and each lay is recorded on a lay slip. After cutting, every ply is stickered so that all panels of one garment come from the same ply. Bundles are ticketed, panels are inspected (often 100 %), and re-cuts come from the same roll or shade. Finally, a reconciliation compares fabric issued against what was laid, end bits, end loss, waste and returns.

### Cited Findings
**Cut order planning / markers**
- Cut order planning (also called lay plan, cut plan or lay lot plan) decides the combination of markers and lays. Marker efficiency is only one part of it — [Apparel Resources, COP](https://apparelresources.com/business-news/manufacturing/fabric-utilization-i-cut-order-planning/)
- Fabric is 50–80 % of garment cost (the article also gives 50–70 %). Spreading cost depends on fabric laid, number of lays and roll changes. Cutting cost depends on bodies cut. Bundling cost depends on qty, bundle size and number of parts — [Apparel Resources](https://apparelresources.com/business-news/manufacturing/fabric-utilization-i-cut-order-planning/)
- A good cut plan keeps plies close to ideal, uses the most markers with the maximum allowed pieces, mixes small and large sizes in each marker, and uses small markers mainly for remnants. Track the variance from ideal plies — [Apparel Resources](https://apparelresources.com/business-news/manufacturing/fabric-utilization-i-cut-order-planning/)
- Marker width should roughly match the usable fabric width to cut edge loss — [textiletrainer](https://textiletrainer.com/?p=12119)
- Case-study marker efficiency is around 85 % — [Apparel Resources](https://apparelresources.com/?p=57341) (one case. Woven shirts and pants are commonly quoted in the 80–90 % range, but I found no authoritative benchmark.)

**Roll grouping (shade / shrinkage / width)**
- Fabric from different dye lots can vary in shade, so factories prepare a shade band. Rolls are allocated by colour, with shade grouping approved before cutting — [Scribd SOP (Vidhu Dyeing)](https://www.scribd.com/document/71896506/Vidhu-Dyeing); shade bands A/B/C/D come from the fabric inspector before spreading — [Scribd Basic Technical SOP for Cutting](https://www.scribd.com/document/143970017/Basic-Technical-SOP-for-Cutting-Section)
- Each roll end carries a sticker with shade no., roll no. and width — [Scribd cutting SOP](https://www.scribd.com/document/143970017/Basic-Technical-SOP-for-Cutting-Section)
- Denim: rolls are grouped by shrinkage, and the pattern is adjusted for each group. One shrinkage group should not exceed about 3 % variation in length or width, and must be sub-grouped beyond that — [textileaid denim shrinkage & shade](https://textileaid.blogspot.com/2018/05/basic-procedures-of-denim-fabric.html); [onlineclothingstudy, Fabric grouping](https://onlineclothingstudy.com/2019/09/what-is-fabric-grouping.html)
- CAD cut-planning tools group rolls by width, by shrinkage per width, by length and by shade, and "you can only group your rolls by one shade" in a lay — [Optitex help, Defining the Marker](https://help.optitex.com/1382687/Content/CutPlan/Creating_New_Cut_Order_with_Fabric_Rolls/Defining_the_Marker_rolls_for_fabric_rolls.htm)
- Denim spreading, cutting and sewing considerations (shade and shrinkage sorting) — [Cotton Inc. CottonWorks](https://cottonworks.com/en/topics/sourcing-manufacturing/denim/spreading-cutting-sewing)

**Spreading**
- Face-to-face spreading folds the fabric at the end of each ply. Folded-end spreads are always face-to-face, while cut-end spreads can be face-to-face or face-one-way. Nap-one-way is used for asymmetric or directional fabric — [textilestudycenter / spreading slides](https://textilestudycenter.com/cutting-section-in-apparel-industry-cutting-room-terminology/); [onlineclothingstudy, spreading modes](https://onlineclothingstudy.com/?p=5896)
- Layering must keep the face side, nap, wale and print direction consistent. Stripe matching at layering uses pin tables or laser beams. Splicing marks are made on the table — [onlineclothingstudy, Cutting process](https://www.onlineclothingstudy.com/2019/12/cutting-process-in-garment-industry.html)
- Automatic spreaders have programmable lay length, end allowance and ply height. A straight knife model is cited at a 6-inch cutting height (machine-specific) — [spreading slides / Scribd](https://www.scribd.com/doc/273907616/Spreading-Machines-1-3)
- Before layering, check whether the fabric needs relaxing and how many hours the lay must rest before cutting — [onlineclothingstudy, 6 checklists](https://www.onlineclothingstudy.com/2015/04/6-things-to-be-considered-prior-to-bulk.html)

**Lay slip / lay report, end bits, end loss**
- The lay slip records lay no., lay length, no. of plies, no. of markers, and plies spread from each roll. End bits and end loss are calculated from it — [onlineclothingstudy, End bits & end loss](https://www.onlineclothingstudy.com/2015/11/what-is-end-bits-and-end-loss-in.html)
- End bits are the fabric left at the end of a roll that is too short for a full marker-length ply. End loss is the allowance at each ply end outside the marker, so 100 plies × 4 cm = 4 m — [onlineclothingstudy](https://www.onlineclothingstudy.com/2015/11/what-is-end-bits-and-end-loss-in.html)
- End loss can be reduced by using fewer plies, controlling the floor, and combining lays into longer spreads — [Apparel Resources](https://apparelresources.com/business-news/manufacturing/fabric-utilization-i-cut-order-planning/)
- Tarasima Apparels used end bits for smaller lays, not only for replacement panels, and reported annual savings of US$758,000 with ProCut — [Apparel Resources case study](https://apparelresources.com/business-news/sourcing/a-case-study-of-tarasima-apparels-fabric-savings-worth-us-758000-achieved-annually-using-procut-and-effective-labour-utilization/) (vendor-linked case study)

**Numbering, bundling, tickets**
- Sequence: cut → move blocks → ply numbering (a sticker on each ply of each component) → sort and bundle → bundling record → bundle ticket → hold for issue to sewing — [onlineclothingstudy, Cutting process](https://www.onlineclothingstudy.com/2019/12/cutting-process-in-garment-industry.html)
- Stickering uses a label machine that prints sequential numbers. Its purpose is to keep components from the same ply together and avoid shade variation within a garment — [onlineclothingstudy, Stickering](https://www.onlineclothingstudy.com/2022/04/what-is-stickering-in-garment-industry.html); [fashion-incubator, shade marking](https://fashion-incubator.com/what-is-shade-marking/)
- A bundle carries its bundle no., style, size and qty. Bundle sizes are commonly about 10–20 pieces — [onlineclothingstudy, Cutting room overview](https://www.onlineclothingstudy.com/2011/01/cutting-room-overview.html). Write the shade reference on each bundle for traceability — [LinkedIn, garment shade control](https://bd.linkedin.com/in/khalid-zahir-7a1aa2194) (practitioner post)

**Cut panel inspection, re-cut, fusing**
- One factory SOP has 100 % cut panel inspection. Defective panels go to a re-cut team, and replacements must come from the same roll or shade group — [Scribd Cutting SOP](https://www.scribd.com/document/488082928/Cutting-SOP-docx)
- Re-cut SOP: identify the cutting no. → find the roll via the roll-wise numbering plan → re-cut from leftover fabric of the same roll, at the same mini-marker position, on the approved hard pattern with the grain line. If that roll is gone, use the same dye lot or shade only with joint approval from the Cutting QC in-charge, Cutting Manager and Cutting In-charge. Log the re-cut in the Re-cut/Replacement log, then Cutting QC checks the panels against the other panels with the same cutting no. Required documents: the roll-wise numbering plan, PO-wise marker plan with mini-marker prints, the hard pattern, and leftover fabric by roll with cut nos. — [Garments-Info, Cut panel replacement SOP](https://garments-information.blogspot.com/2019/04/cut-panel-replacement-sop-standard-operating-procedure.html)
- Not all factories do panel checking, and some check only large parts. Re-cut reports should record the panel no. and the roll used — [onlineclothingstudy, QC systems](https://onlineclothingstudy.com/2021/07/quality-control-systems-for-quality.html)
- Cut-part inspection suits large parts with few pieces. Small parts in high counts (shirts) are better inspected during sewing. During a re-cut, the matching end bit is pulled by sticker number, and other good parts with that sticker are held — [Apparel Resources, Cut part inspection](https://apparelresources.com/business-news/manufacturing/fabric-inspection-cut-part-inspection/)
- Replacement fabric options: end bits from the lay, fresh fabric, or parts from another garment. The choice depends on later processing (for example, wash), fabric type and embellishment — [Slideshare QC](https://fr2.slideshare.net/zamandu/quality-control-58218985)
- Fusing is an optional cutting sub-process for collars, cuffs and similar parts. When panels are printed or embroidered, they are matched to their other components at bundling — [onlineclothingstudy, Cutting process](https://www.onlineclothingstudy.com/2019/12/cutting-process-in-garment-industry.html)

**Reconciliation and KPIs**
- Fabric reconciliation analyses how purchased fabric was used: issued to cutting, consumed, used for alterations, end bits and cutting waste, and returned to store after shipment. It is often run by the store or audit — [onlineclothingstudy, Fabric reconciliation](https://www.onlineclothingstudy.com/2013/08/fabric-reconciliation-procedure-for.html)
- Reconciliation compares the length recorded on the lay sheet with the roll ticket length. It shows what was bought, issued, laid, short from the supplier, unusable, and left as end bits and off-cuts, and the profit or loss against costed consumption — [Scribd, Controlling fabric usage](https://www.scribd.com/doc/221546357/Controlling-Fabric-Usage)
- About 13 % of purchased fabric is reported lost to dead stock, cutting loss, rejects and short rolls — [Apparel Resources, Fabric management](https://apparelresources.com/business-news/manufacturing/fabric-management-saving-fabric-or-just-increasing-dead-stock/). Style reconciliation reports often expose dead stock — [Apparel Resources case](https://apparelresources.com/business-news/sourcing/a-case-study-of-tarasima-apparels-fabric-savings-worth-us-758000-achieved-annually-using-procut-and-effective-labour-utilization/)
- ILO FIT cutting module (CR8): Re-cuts % is calculated per cut order and averaged monthly, owned by the cutting manager and QC. Fabric utilization % is also a KPI — [ILO/Asia Garment Hub CR8 (search snippet; the PDF returned 403)](https://asiagarmenthub.net/resources/2021/cr8-cut-inspection-cutting-room-operations-pdfen.pdf/@@download/file/CR8-Cut-inspection-Cutting-room-operations-PDFEN.pdf)
- Other cutting KPIs: marker efficiency, fabric utilization, cutting quality, machine and manpower utilization — [onlineclothingstudy, IE in cutting](https://www.onlineclothingstudy.com/2014/10/involvement-of-industrial-engineers-in.html)

### Inferences
- (Design) Documents and doctypes: Fabric Roll (roll no., dye lot, shade band, shrinkage group warp/weft %, cuttable width, ticket length, actual length, inspection points) → Cut Order Plan (lays, each with a marker ref, size ratio, marker length, efficiency %, planned plies, shade group, fabric component) → Lay Report (per lay: rolls used, plies per roll, roll length in vs end bit out, splices, end loss, actual plies, damages) → Bundle (bundle no., cut no./lay no., style, colour, size, shade/roll, sticker range from–to, qty, component, destination/PO) → Cut Panel Inspection / Re-cut log → Fabric Reconciliation per cut order and per style.
- Hard rules to enforce: one lay = one shade group (and for denim, one shrinkage group, which is tied to a pattern version). All panels of a garment come from one ply (enforced through sticker ranges). A re-cut must reference the original roll, or a same-lot roll with recorded approval. Bulk cutting cannot start without approvals of pilot, pattern, shade band and marker consumption.
- Ply height limits are machine- and fabric-specific, so store a max-ply parameter per fabric type and cutting machine. (Practitioner range, unsourced: straight-knife lays for shirting are often under about 100–150 plies, and for denim less. Auto cutters are limited by compressed height, for example a few cm.)
- Bundle tickets should be printable with barcode or QR for WIP scanning. They should carry the ply/sticker range and shade so that sewing does not mix shades.

### Gaps
- I could not fetch the ILO FIT CR8 module PDF (403), so its exact inspection sampling and KPI formulas are unconfirmed beyond the snippet.
- I found no authoritative public ply-height or end-allowance standards (common practitioner end allowance of about 1–2 cm per end is unsourced).
- I found no published marker efficiency benchmarks by product (shirts, pants, denim).

## Formulas

### Takeaway
The formulas are well established in practitioner sources: marker efficiency, marked vs lay consumption, weighted efficiency, ideal plies, cut-to-ship, and fabric utilization. Definitions of "utilization" and "achieved consumption" differ between sources, so the ERP must define each one explicitly.

### Cited Findings
- Marker efficiency % = (total area of pattern pieces in marker ÷ marker area [length × width]) × 100 — [textiletrainer](https://textiletrainer.com/?p=12119); [uphance](https://uphance.com/blog/what-is-marker-making/)
- Marked consumption = Σ marker lengths ÷ bodies marked (9.76 ÷ 8 = 1.220 m). Lay consumption = Σ (marker length × plies) ÷ pieces cut (48.36 ÷ 40 = 1.209 m) — [Apparel Resources COP](https://apparelresources.com/business-news/manufacturing/fabric-utilization-i-cut-order-planning/)
- Weighted marker efficiency = Σ (efficiency × plies) ÷ total plies (example 76.67 %). Ideal plies = order qty ÷ max pieces per marker. Waste per ply = marker length × width × (1 − efficiency) — [Apparel Resources](https://apparelresources.com/business-news/manufacturing/fabric-utilization-i-cut-order-planning/)
- Cut qty = order qty × (1 + extra %). Cut-to-ship = cut qty ÷ shipped qty — [onlineclothingstudy](https://onlineclothingstudy.com/2013/10/what-is-cut-to-ship-ratio-in-apparel.html)
- Fabric utilization = fabric used in garments ÷ total fabric available (example 487/640 = 76.1 %). Cutting-room achieved consumption = fabric issued to cutting ÷ garments cut and issued to sewing. Factory-level consumption = fabric bought ÷ garments shipped — [Scribd, Controlling Fabric Usage](https://www.scribd.com/doc/221546357/Controlling-Fabric-Usage)
- End loss = plies × end allowance per ply — [onlineclothingstudy](https://www.onlineclothingstudy.com/2015/11/what-is-end-bits-and-end-loss-in.html)

### Inferences
- (Design) Suggested ERP set, all per fabric component:
  - costed consumption (from the cost sheet)
  - marker consumption, which is lay consumption from the cut plan
  - actual consumption = (fabric issued − returned to store − end bits held reusable) ÷ good pieces cut
  - variance % = (actual − costed) ÷ costed
  - fabric utilization = marker-used fabric ÷ fabric issued
  - cut vs order % = actual cut ÷ order qty − 1
  - cut-to-ship = actual cut ÷ shipped
  - re-cut % = re-cut panels ÷ total panels cut (or by garment equivalents)
- Units: woven fabric in Vietnam is bought in yards or metres. Normalise per fabric and store the cuttable width, because consumption in yards is only valid at a given width.

### Gaps
- No standard definition of "fabric utilization" was found. Sources use different denominators (fabric issued vs fabric bought).

## Edge cases

### Takeaway
Most edge cases come down to two things: fabric that does not match the plan (short, partial, mixed shade, mixed width or mixed shrinkage) and order structure (multiple destinations, multiple fabric components, directional or check fabric). The sources describe the controls (grouping, same-roll re-cut, approval of consumption variation) but rarely the exact ERP handling.

### Cited Findings
- Short fabric: if marker consumption is higher than sampling consumption, the factory "may run short and produce less than order qty". The variation must be approved — [onlineclothingstudy, 6 checklists](https://www.onlineclothingstudy.com/2015/04/6-things-to-be-considered-prior-to-bulk.html). Supplier short rolls are part of the reported ~13 % loss — [Apparel Resources](https://apparelresources.com/business-news/manufacturing/fabric-management-saving-fabric-or-just-increasing-dead-stock/)
- Mixed shade bands: only one shade per lay group — [Optitex](https://help.optitex.com/1382687/Content/CutPlan/Creating_New_Cut_Order_with_Fabric_Rolls/Defining_the_Marker_rolls_for_fabric_rolls.htm). Ply stickering prevents shade mixing within a garment — [onlineclothingstudy, Stickering](https://www.onlineclothingstudy.com/2022/04/what-is-stickering-in-garment-industry.html)
- Roll width variation: group rolls by width, because different widths need different markers — [Optitex](https://help.optitex.com/1382687/Content/CutPlan/Creating_New_Cut_Order_with_Fabric_Rolls/Defining_the_Marker_rolls_for_fabric_rolls.htm); [onlineclothingstudy, Fabric grouping](https://onlineclothingstudy.com/2019/09/what-is-fabric-grouping.html)
- Shrinkage variation (denim): sub-group rolls beyond about 3 % and use a separate pattern for each group — [textileaid](https://textileaid.blogspot.com/2018/05/basic-procedures-of-denim-fabric.html)
- Re-cut after damage: same roll, or same lot with approval, at the mini-marker position — [Garments-Info SOP](https://garments-information.blogspot.com/2019/04/cut-panel-replacement-sop-standard-operating-procedure.html)
- Directional, nap and print fabrics: use nap-one-way / face-one-way spreading. Stripes and checks are matched at layering with pin tables or lasers — [onlineclothingstudy, Cutting process](https://www.onlineclothingstudy.com/2019/12/cutting-process-in-garment-industry.html); [onlineclothingstudy, spreading modes](https://onlineclothingstudy.com/?p=5896)
- Remnant markers raise plies above ideal, and small markers are used for remnants — [Apparel Resources](https://apparelresources.com/business-news/manufacturing/fabric-utilization-i-cut-order-planning/)
- Excess cut is partly an intentional buffer, and some buyers accept overage at the same FOB — [onlineclothingstudy](https://onlineclothingstudy.com/2013/10/what-is-cut-to-ship-ratio-in-apparel.html)

### Inferences (design recommendations; not sourced)
- **Partial fabric arrival:** allow a cutting order to be split into several cut orders or lays, released only for colours or shade lots whose fabric is inspected and approved. Track the remaining-to-cut balance for each colour × size.
- **Short fabric:** before cutting, re-plan the size ratio to protect key sizes, or ask the buyer to accept a short shipment. Record a "short-cut approval" with a reason and buyer confirmation. Raise a fabric claim against the mill using the inspection and reconciliation data.
- **Mixed shade bands within a colour:** cut each shade band as its own lay or sub-lot. Keep shade on the bundle and carry it through sewing, washing and packing, so a carton or pack holds one shade if the buyer requires it. Washing can also create shade variation, which the subcontractor must handle with shade grouping after wash.
- **Size missing from a lay:** allow lays whose size ratio covers only a subset of sizes. Check total cut per size against the plan across all lays, and flag both under- and over-cut sizes.
- **Excess cut beyond tolerance:** flag when actual cut is above order × (1 + max allowed %), and require approval. Track over-produced garments as stock or for disposal.
- **Multiple ship-to destinations:** cut by colour and size, then allocate bundles or finished goods to destination. Alternatively, cut per destination when labels or care labels differ. In that case destination must be a dimension on the cut order and the bundle.
- **Multiple fabrics per style:** each component (shell, lining, pocketing, fusing/interlining, contrast) gets its own marker, consumption, roll allocation and reconciliation. All components must be complete (the "kit") before a bundle is released to sewing. Pocketing and lining usually need no shade matching to the shell, but contrast fabric does.
- **Check / stripe matching:** use a lower marker efficiency target, add matching allowance (blocking), and possibly block-cut and then re-cut. Consumption is set separately from solid fabric.
- **Wash shrinkage:** the pattern version used must be tied to the shrinkage group. If the wash subcontractor's result varies from batch to batch, the pilot must use the same wash recipe and the same subcontractor as bulk.

### Gaps
- I found no public sources on how apparel ERPs (WFX, BlueCherry, Gerber AccuMark cut planning) handle multi-destination cut allocation or short-cut approvals.
- I found no published guidance on how extra-cut percentages should differ for washed denim vs non-washed shirts, beyond "varies with number of processes".
