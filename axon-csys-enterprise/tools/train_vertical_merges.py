#!/usr/bin/env python3
# §Fase 27.e — Vertical BPE merges trainer for axon-csys-enterprise.
#
# Trains tiktoken-compatible BPE merges over a per-vertical corpus and
# emits a binary `.bin` file in the OSS axon-csys 0.1.x wire format
# (the same one consumed by the OSS BPE engine). The output is dropped
# into `axon-csys-enterprise/c-src/tokens/merges_<vertical>_v1_seed.bin`.
#
# Two run modes:
#
#   1. Seed mode (default — `python train_vertical_merges.py`):
#      Trains using the curated public-domain seed corpora embedded in
#      this file. Produces the `_v1_seed.bin` artefacts that ship with
#      the v0.1.0 enterprise crate. Reproducible: same seed corpus
#      + same target vocab → same bytes (deterministic byte-output
#      verified by 27.e drift-gate tests).
#
#   2. Adopter retrain (`python train_vertical_merges.py --corpus
#      /path/to/medical_full.txt --vertical medical --target-vocab 32000`):
#      Adopters with their own corpus retrain to produce production-
#      scale encoders. The output filename is suffixed with the corpus
#      hash for provenance.
#
# Wire format mirrors OSS `gen_merges.py` exactly (file consumed by
# the same C kernel):
#
#   offset  bytes  field
#   ──────  ─────  ─────
#   0       4      magic "AXBP" (0x42505841)
#   4       4      version u32 = 1
#   8       4      vocab_size u32
#   12      4      regex_pat_len u32
#   16      N      regex_pat (UTF-8)
#   16+N    4      entries_byte_count u32 (sanity)
#   20+N    …      entries: [u8 len][bytes][u32 LE rank]
#
# Seed corpora (D6 ratified — open / public-domain only for v1.0):
#
#   - medical_v1_seed: curated vocabulary spanning common ICD-10 /
#     SNOMED-CT terminology, FDA-approved drug names (Orange Book is
#     public domain), anatomical nomenclature, lab test names. Source:
#     this file (see CORPUS_MEDICAL below). Adopter retrain target:
#     PubMed Central full-text + MedlinePlus + RxNorm.
#
#   - legal_v1_seed: curated vocabulary spanning federal court
#     procedural language, contract clause boilerplate, standard
#     citation formats, statutory language. Source: this file. Adopter
#     retrain target: CourtListener public US case law + SEC EDGAR
#     filings + UK statutory instruments.
#
#   - fintech_v1_seed: curated vocabulary spanning SEC EDGAR financial
#     filing terminology, FFIEC AML/KYC/BSA terms, ECB monetary
#     stability language, SOX compliance vocabulary. Source: this file.
#     Adopter retrain target: SEC EDGAR financial reports + FFIEC public
#     guidance + ECB monetary stability reports.
#
# All three seed corpora are curated by hand from public-domain
# regulatory + clinical glossaries; no copyrighted text is reproduced.
#
# BPE algorithm (Sennrich et al. 2015 + tiktoken's variant):
#
#   1. Pretokenise corpus using the cl100k_base regex pattern
#      (vertical text follows English text patterns; reusing cl100k
#      gives byte-identical compatibility with the OSS pretokeniser).
#   2. Initialise vocabulary with the 256 single-byte tokens (ranks
#      0..255). This guarantees full byte coverage — any byte sequence
#      can be fall-back-encoded as a single byte.
#   3. Tokenise each pretokenised piece into a list of single-byte
#      token IDs (i.e. the byte values themselves).
#   4. Iteratively find the most frequent adjacent pair across all
#      pieces; merge it into a new vocabulary token at the next rank.
#      Stop when target_vocab_size reached or no pair appears more
#      than `min_freq` times.
#   5. Emit the (bytes, rank) dict in the OSS .bin format.

from __future__ import annotations

import argparse
import collections
import hashlib
import re
import struct
import sys
from pathlib import Path

MAGIC = b"AXBP"
VERSION = 1

# Reuse cl100k_base's pretokenizer pattern. Vertical corpora are
# English text + numbers + standard punctuation; the cl100k pattern
# handles all of these correctly. Using a vertical-specific pattern
# would diverge from OSS pretokeniser semantics + break drift gate.
PAT_CL100K = (
    r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+|"
    r" ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s"
)

# Python `re` does not support \p{L} / \p{N} — use the third-party
# `regex` library when available; otherwise fall back to a simpler
# ASCII-only pretokeniser. The seed corpora are all ASCII-clean so
# the fallback produces equivalent results for them; adopter retrain
# with non-ASCII corpora SHOULD install `regex` for correctness.
try:
    import regex as _regex_lib

    _PRETOK_RE = _regex_lib.compile(PAT_CL100K)

    def _pretokenise(text: str) -> list[bytes]:
        return [m.encode("utf-8") for m in _PRETOK_RE.findall(text)]
except ImportError:
    _ASCII_PRETOK = re.compile(
        r"'(?:[sSdDmMtT]|ll|ve|re|LL|VE|RE)"
        r"|[^\r\n\sA-Za-z0-9]?[A-Za-z]+"
        r"|[0-9]{1,3}"
        r"| ?[^\s\w]+[\r\n]*"
        r"|\s+",
    )

    def _pretokenise(text: str) -> list[bytes]:
        return [m.encode("utf-8") for m in _ASCII_PRETOK.findall(text)]


# ─────────────────────────────────────────────────────────────────────
# BPE training core
# ─────────────────────────────────────────────────────────────────────


def _piece_to_ids(piece: bytes) -> list[int]:
    """Initial tokenisation: each byte is its own token (rank == byte value)."""
    return list(piece)


def _count_pairs(
    pieces: list[list[int]],
    piece_freq: list[int],
) -> collections.Counter[tuple[int, int]]:
    """Count adjacent-pair frequencies across all pieces, weighted by
    piece frequency. Returns Counter[(left_id, right_id) → freq]."""
    counts: collections.Counter[tuple[int, int]] = collections.Counter()
    for piece, freq in zip(pieces, piece_freq):
        if len(piece) < 2:
            continue
        for i in range(len(piece) - 1):
            counts[(piece[i], piece[i + 1])] += freq
    return counts


def _apply_merge(
    pieces: list[list[int]],
    merge_pair: tuple[int, int],
    new_id: int,
) -> None:
    """Replace every occurrence of `merge_pair` in every piece with
    `new_id`. Mutates `pieces` in place."""
    a, b = merge_pair
    for piece_idx, piece in enumerate(pieces):
        if len(piece) < 2:
            continue
        out: list[int] = []
        i = 0
        while i < len(piece):
            if i < len(piece) - 1 and piece[i] == a and piece[i + 1] == b:
                out.append(new_id)
                i += 2
            else:
                out.append(piece[i])
                i += 1
        pieces[piece_idx] = out


def train_bpe(
    corpus_text: str,
    target_vocab_size: int,
    min_pair_freq: int = 1,
) -> dict[bytes, int]:
    """Train BPE merges over `corpus_text`. Returns a dict
    `{token_bytes: rank}` covering the 256 byte tokens + every learned
    merge. Stops at `target_vocab_size` or when no pair has ≥
    `min_pair_freq` occurrences (whichever comes first)."""
    if target_vocab_size < 256:
        raise ValueError("target_vocab_size must be >= 256 (covers byte alphabet)")

    # Pretokenise + count piece frequencies (BPE operates piece-wise
    # so identical pieces collapse).
    raw_pieces = _pretokenise(corpus_text)
    piece_counts = collections.Counter(raw_pieces)

    pieces_unique: list[bytes] = list(piece_counts.keys())
    pieces_freq: list[int] = [piece_counts[p] for p in pieces_unique]
    piece_ids: list[list[int]] = [_piece_to_ids(p) for p in pieces_unique]

    # Vocabulary starts with the 256 byte tokens.
    vocab: dict[bytes, int] = {bytes([b]): b for b in range(256)}
    # `id_to_bytes`: rank → token_bytes. Used to assemble the bytes of
    # a merged-pair-id by concatenating its operands.
    id_to_bytes: dict[int, bytes] = {b: bytes([b]) for b in range(256)}

    next_id = 256
    while next_id < target_vocab_size:
        pair_counts = _count_pairs(piece_ids, pieces_freq)
        if not pair_counts:
            break
        best_pair, best_freq = pair_counts.most_common(1)[0]
        if best_freq < min_pair_freq:
            break

        # Assemble the merged token's byte sequence.
        merged_bytes = id_to_bytes[best_pair[0]] + id_to_bytes[best_pair[1]]
        if merged_bytes in vocab:
            # Already in vocab — shouldn't happen in normal training,
            # but defensive: drop the pair from this iteration's pool.
            # Skip this pair by mutating it out so the next round picks
            # a different one.
            _apply_merge(piece_ids, best_pair, vocab[merged_bytes])
            continue

        vocab[merged_bytes] = next_id
        id_to_bytes[next_id] = merged_bytes
        _apply_merge(piece_ids, best_pair, next_id)
        next_id += 1

    return vocab


# ─────────────────────────────────────────────────────────────────────
# Wire format serialisation (mirrors OSS gen_merges.py)
# ─────────────────────────────────────────────────────────────────────


def serialise(vocab: dict[bytes, int], pat: str = PAT_CL100K) -> bytes:
    """Emit `vocab` as the OSS axon-csys 0.1.x .bin wire format."""
    pat_bytes = pat.encode("utf-8")
    items = sorted(vocab.items(), key=lambda kv: kv[1])

    body_parts: list[bytes] = []
    for token_bytes, rank in items:
        if not 1 <= len(token_bytes) <= 255:
            raise ValueError(
                f"token {token_bytes!r} length {len(token_bytes)} out of u8 range"
            )
        body_parts.append(struct.pack("<B", len(token_bytes)))
        body_parts.append(token_bytes)
        body_parts.append(struct.pack("<I", rank))
    body = b"".join(body_parts)

    header = (
        MAGIC
        + struct.pack("<I", VERSION)
        + struct.pack("<I", len(items))
        + struct.pack("<I", len(pat_bytes))
        + pat_bytes
        + struct.pack("<I", len(body))
    )
    return header + body


# ─────────────────────────────────────────────────────────────────────
# Curated public-domain seed corpora (D6 ratified)
# ─────────────────────────────────────────────────────────────────────
#
# Each seed corpus is hand-curated from public-domain regulatory /
# clinical glossaries. They are deliberately small (~3-5 KB each) and
# vertical-jargon-dense so BPE training picks up the domain tokens.
# Adopters retrain on full corpora via the --corpus flag.

CORPUS_MEDICAL = """
Patient presents with acute myocardial infarction; ECG shows ST-elevation in leads II, III, aVF.
Diagnosis: inferior wall STEMI. Door-to-balloon time 73 minutes.
History of hypertension, type 2 diabetes mellitus, hyperlipidemia. Current medications: metformin 500mg BID, lisinopril 20mg daily, atorvastatin 40mg HS.
Echocardiogram demonstrates ejection fraction 35%, regional wall motion abnormality of inferior wall, mild mitral regurgitation.
Cardiac catheterization reveals 99% occlusion of the right coronary artery; successful percutaneous coronary intervention with drug-eluting stent placement.
Post-procedure: dual antiplatelet therapy with aspirin 81mg and clopidogrel 75mg. Beta-blocker initiated: metoprolol succinate 25mg.
ACE inhibitor titrated: lisinopril increased to 40mg daily for cardioprotection.
HbA1c 8.2%; will adjust diabetic regimen. Consider GLP-1 receptor agonist or SGLT2 inhibitor.
Chest X-ray: clear lung fields, no acute cardiopulmonary process. Cardiomegaly noted.
Labs: troponin I peak 14.2 ng/mL, CK-MB 92 U/L, BNP 850 pg/mL.
Renal function: creatinine 1.1 mg/dL, eGFR 68 mL/min/1.73m2.
CBC: WBC 9.8, hemoglobin 13.2, platelets 241.
Lipid panel: total cholesterol 184, LDL 102, HDL 38, triglycerides 220.
Basic metabolic panel: sodium 138, potassium 4.2, chloride 102, bicarbonate 24, BUN 22, glucose 178.
Allergies: penicillin causes urticaria. NKDA otherwise.
Surgical history: appendectomy 2008, cholecystectomy 2015, total knee arthroplasty right 2019.
Family history: father MI age 58, mother breast cancer age 67, sister type 1 diabetes.
Social history: former smoker quit 2010, occasional alcohol use, no illicit drug use.
Review of systems: denies chest pain, dyspnea, palpitations, edema, syncope.
Physical exam: vital signs stable. Heart regular rate and rhythm, no murmurs. Lungs clear to auscultation bilaterally. Abdomen soft, nontender. Extremities without edema.
Plan: continue dual antiplatelet therapy, beta-blocker, ACE inhibitor, statin. Cardiac rehabilitation referral. Outpatient cardiology follow-up in two weeks.
ICD-10: I21.19 ST elevation myocardial infarction involving other coronary artery of inferior wall.
ICD-10: I10 essential primary hypertension. ICD-10: E11.9 type 2 diabetes mellitus without complications. ICD-10: E78.5 hyperlipidemia unspecified.
SNOMED CT: 22298006 myocardial infarction. SNOMED CT: 38341003 hypertensive disorder. SNOMED CT: 44054006 diabetes mellitus type 2.
Procedure: percutaneous transluminal coronary angioplasty with stent placement.
Pneumonia diagnosed via chest CT showing right lower lobe consolidation. Started empirical antibiotic therapy: ceftriaxone and azithromycin per IDSA guidelines.
Sepsis with septic shock secondary to community-acquired pneumonia. Required vasopressor support with norepinephrine.
Acute kidney injury stage 2 per KDIGO criteria. Creatinine baseline 1.0, peak 2.4 mg/dL.
Acute respiratory distress syndrome requiring mechanical ventilation. PaO2/FiO2 ratio 165, indicating moderate ARDS.
Endotracheal intubation with rapid sequence induction. Sedation with propofol and fentanyl infusion.
Sputum culture grew Streptococcus pneumoniae sensitive to ceftriaxone.
Blood cultures positive for methicillin-resistant Staphylococcus aureus. Vancomycin initiated.
Echocardiogram showed septic emboli concerning for endocarditis. Transesophageal echo confirmed mitral valve vegetation.
Infectious disease consult recommended six-week course of vancomycin per IDSA endocarditis guidelines.
Patient developed acute pulmonary edema. Furosemide 80mg IV given with good diuresis.
Atrial fibrillation with rapid ventricular response. Diltiazem drip initiated for rate control.
CHA2DS2-VASc score 4, anticoagulation with apixaban 5mg twice daily.
Stroke neurology consulted; brain MRI shows acute ischemic stroke in middle cerebral artery territory.
NIH Stroke Scale 8. Thrombolytic therapy with alteplase administered within window.
CT angiography demonstrates left M1 occlusion. Mechanical thrombectomy performed with TICI 3 reperfusion.
Diabetic ketoacidosis with anion gap 22, glucose 480, beta-hydroxybutyrate 4.5.
Insulin drip protocol initiated, fluids with normal saline, electrolyte replacement.
Asthma exacerbation with peak flow 35% predicted. Albuterol nebulization, ipratropium, methylprednisolone IV.
Chronic obstructive pulmonary disease with acute exacerbation. Tiotropium maintenance, prednisone taper, azithromycin.
Cellulitis of the left lower extremity. Cefazolin IV for streptococcal coverage.
Urinary tract infection with pyuria and bacteriuria. Empirical ceftriaxone pending culture sensitivity.
Cholecystitis confirmed by ultrasound: gallbladder wall thickening, pericholecystic fluid, sonographic Murphy sign.
Surgical intervention recommended: laparoscopic cholecystectomy.
Appendicitis with rebound tenderness at McBurney point. Open appendectomy performed.
Diverticulitis without abscess. Conservative management with bowel rest and antibiotics.
Inflammatory bowel disease flare. Methylprednisolone IV with biologic therapy continuation.
Hepatocellular carcinoma diagnosed on triple-phase CT. AFP elevated. Hepatology consult.
Pancreatic adenocarcinoma with hepatic metastases. Palliative chemotherapy discussed.
Breast cancer with sentinel lymph node biopsy positive. Adjuvant chemotherapy and radiation therapy planned.
Prostate cancer Gleason 7 (3+4). Active surveillance versus radical prostatectomy discussed.
Multiple sclerosis with relapse confirmed on brain MRI showing new T2 lesions. Methylprednisolone pulse therapy.
Parkinson disease with worsening tremor. Carbidopa-levodopa dose increased.
Alzheimer disease with moderate cognitive impairment. Donepezil and memantine initiated.
Major depressive disorder. Sertraline started, cognitive behavioral therapy referral.
Generalized anxiety disorder. Buspirone trial, mindfulness-based stress reduction.
Bipolar disorder type I, manic episode. Hospitalization, lithium initiation, olanzapine adjunct.
Schizophrenia with auditory hallucinations. Risperidone maintenance, supportive psychotherapy.
Substance use disorder, opioid type. Buprenorphine-naloxone maintenance therapy.
Hypothyroidism. Levothyroxine 50mcg daily titrated by TSH.
Hyperthyroidism, Graves disease. Methimazole and beta-blocker for symptom control.
Adrenal insufficiency. Hydrocortisone replacement, fludrocortisone for mineralocorticoid effect.
Anemia of chronic disease. Iron studies normal, erythropoietin trial.
Thrombocytopenia, immune-mediated. IVIG and corticosteroids.
Deep vein thrombosis confirmed by Doppler ultrasound. Anticoagulation with enoxaparin bridged to warfarin.
Pulmonary embolism with right ventricular strain. Thrombolytic therapy considered for high-risk PE.
Hypertensive emergency with end-organ damage. Nicardipine drip, gradual blood pressure reduction.
Aortic dissection type A. Emergent cardiothoracic surgery consult.
Aortic aneurysm 5.8 cm. Vascular surgery referral for elective repair.
Subarachnoid hemorrhage from ruptured cerebral aneurysm. Neurosurgical clipping versus endovascular coiling.
Traumatic brain injury, severe. Glasgow Coma Scale 6, intracranial pressure monitoring.
Spinal cord injury, complete C5. Acute rehabilitation, methylprednisolone protocol.
Pregnancy at 32 weeks with preeclampsia. Magnesium sulfate seizure prophylaxis.
Eclampsia with convulsion. Emergent cesarean section performed.
Postpartum hemorrhage, atonic. Oxytocin, methylergonovine, uterine massage.
Neonatal respiratory distress syndrome. Surfactant replacement, CPAP support.
Pediatric asthma, severe exacerbation. Magnesium sulfate IV, continuous albuterol nebulization.
Pediatric meningitis. Ceftriaxone and vancomycin pending CSF cultures.
Geriatric delirium, hospital-acquired. Nonpharmacologic interventions, address contributing factors.
Hospice consultation for advanced metastatic cancer. Goals of care discussion held.
Palliative care consult for symptom management. Morphine for pain and dyspnea.
Vaccinations updated: influenza, pneumococcal, zoster as appropriate.
Preventive care: colonoscopy due, mammography current, Pap smear current.
Health maintenance: lipid panel within target, HbA1c at goal, blood pressure controlled.
Smoking cessation counseling provided. Nicotine replacement therapy offered.
Alcohol use screening with AUDIT-C, score 5, brief intervention provided.
Domestic violence screening, negative. Resources provided.
Mental health screening with PHQ-9, score 8 indicating mild depression.
"""

CORPUS_LEGAL = """
Plaintiff brings this action pursuant to Federal Rule of Civil Procedure 23 seeking class certification.
Defendant moves to dismiss pursuant to Rule 12(b)(6) for failure to state a claim upon which relief can be granted.
The Court has subject matter jurisdiction pursuant to 28 U.S.C. Section 1332 based on diversity of citizenship and amount in controversy exceeding seventy-five thousand dollars exclusive of interest and costs.
Venue is proper in this district pursuant to 28 U.S.C. Section 1391(b) because a substantial part of the events giving rise to the claim occurred in this district.
Plaintiff hereby demands a jury trial on all issues so triable pursuant to Federal Rule of Civil Procedure 38.
Counsel for the parties have met and conferred pursuant to Federal Rule of Civil Procedure 26(f).
The discovery deadline shall be one hundred eighty days from the date of this order.
Dispositive motions shall be filed no later than ninety days following the close of discovery.
The Court grants Plaintiffs' motion for class certification under Federal Rule of Civil Procedure 23(b)(3).
Class members satisfy the requirements of numerosity, commonality, typicality, and adequacy of representation.
Common questions of law and fact predominate over questions affecting only individual members.
A class action is superior to other available methods for the fair and efficient adjudication of this controversy.
The Court appoints lead counsel pursuant to Federal Rule of Civil Procedure 23(g) and the Private Securities Litigation Reform Act.
Defendant's motion for summary judgment is denied. Genuine disputes of material fact remain for trial.
Pursuant to Federal Rule of Civil Procedure 56(a), summary judgment is appropriate only when there is no genuine dispute as to any material fact.
The Court reviews the evidence in the light most favorable to the non-moving party and draws all reasonable inferences in favor of the non-moving party.
Plaintiff has stated a plausible claim for relief sufficient to survive the motion to dismiss under the standards of Bell Atlantic Corp. v. Twombly and Ashcroft v. Iqbal.
The complaint alleges sufficient factual matter, accepted as true, to state a claim that is plausible on its face.
Defendant breached the contract by failing to deliver conforming goods on the date specified in the purchase order.
The contract is governed by the Uniform Commercial Code Article 2 as adopted by the State of New York.
Plaintiff seeks damages including expectation damages, consequential damages, and incidental damages pursuant to UCC Section 2-715.
Defendant's affirmative defenses of accord and satisfaction, waiver, and laches are without merit.
The Court finds that the parties had a valid and enforceable contract supported by mutual consideration.
The contract was breached when Defendant failed to perform its obligations as specified in Section 4.2 of the agreement.
Plaintiff is entitled to specific performance pursuant to the equitable powers of this Court.
The non-disclosure agreement contains valid restrictive covenants reasonably necessary to protect legitimate business interests.
The non-compete clause is reasonable in geographic scope and duration.
Defendant violated the non-disclosure agreement by misappropriating confidential information and trade secrets.
Plaintiff seeks injunctive relief pursuant to the Defend Trade Secrets Act of 2016.
Patent infringement claims are governed by 35 U.S.C. Section 271 et seq.
Defendant's product literally infringes claims 1, 4, and 7 of U.S. Patent No. 9,876,543 under the doctrine of equivalents.
Plaintiff seeks injunctive relief pursuant to 35 U.S.C. Section 283 and damages pursuant to 35 U.S.C. Section 284.
Reasonable royalty analysis under the Georgia-Pacific factors yields a base royalty rate of three percent of sales.
Lost profits damages pursuant to the Panduit factors are quantified at twelve million dollars.
Trademark infringement is established under the Lanham Act 15 U.S.C. Section 1114.
The marks are likely to cause consumer confusion under the Polaroid factors.
Defendant's use of the mark dilutes the famous nature of Plaintiff's mark in violation of 15 U.S.C. Section 1125(c).
Copyright infringement requires proof of ownership and copying of constituent elements of the work that are original.
Substantial similarity is established by the ordinary observer test as applied in Arnstein v. Porter.
The defense of fair use is rejected. The four factors of 17 U.S.C. Section 107 weigh in favor of Plaintiff.
The defendant pleads not guilty to all counts of the indictment.
Defendant invokes Fifth Amendment privilege against self-incrimination.
The Court appointed counsel for the defendant pursuant to the Sixth Amendment.
Bail is set at two hundred fifty thousand dollars or surety bond.
The grand jury returned a true bill on counts of mail fraud and wire fraud under 18 U.S.C. Sections 1341 and 1343.
Defendant moves to suppress evidence obtained pursuant to a search warrant alleging Fourth Amendment violation.
The good faith exception to the exclusionary rule under United States v. Leon does not apply where the warrant is facially deficient.
Miranda warnings were administered prior to custodial interrogation per Miranda v. Arizona.
The defendant knowingly and voluntarily waived her Miranda rights.
The plea agreement provides for a sentence within the United States Sentencing Guidelines range.
Defendant accepts responsibility under USSG Section 3E1.1, reducing the offense level by three.
The Court accepts the defendant's plea of guilty as knowing, voluntary, and supported by an adequate factual basis.
Sentencing will be conducted following the preparation of a presentence investigation report.
Pursuant to 18 U.S.C. Section 3553(a), the Court considers the nature and circumstances of the offense and the history and characteristics of the defendant.
The defendant is sentenced to seventy-eight months imprisonment followed by three years supervised release.
Restitution is ordered pursuant to the Mandatory Victims Restitution Act of 1996.
The defendant has the right to appeal the conviction and sentence within fourteen days pursuant to Federal Rule of Appellate Procedure 4.
Defendant filed a notice of appeal to the United States Court of Appeals for the Second Circuit.
The appellate brief addresses the standard of review for evidentiary rulings: abuse of discretion.
The brief argues that the district court committed reversible error by admitting hearsay evidence.
Statements offered for the truth of the matter asserted are inadmissible hearsay under Federal Rule of Evidence 801.
Exceptions to the hearsay rule are codified in Federal Rule of Evidence 803.
Business records exception under FRE 803(6) requires foundation by a custodian or other qualified witness.
The recorded recollection exception under FRE 803(5) requires the witness to have once had personal knowledge.
Expert testimony is governed by Daubert v. Merrell Dow Pharmaceuticals and Federal Rule of Evidence 702.
The proposed expert testimony fails the reliability prong of the Daubert analysis.
Discovery includes interrogatories, requests for production, requests for admission, and depositions pursuant to Federal Rules of Civil Procedure 26 through 37.
Privileged communications between attorney and client are protected by the attorney-client privilege.
The work product doctrine protects materials prepared in anticipation of litigation under Hickman v. Taylor and Federal Rule of Civil Procedure 26(b)(3).
Plaintiff seeks sanctions for spoliation of evidence pursuant to the Court's inherent authority and Federal Rule of Civil Procedure 37(e).
Defendant failed to preserve electronically stored information after the duty to preserve attached.
The duty to preserve evidence arises when litigation is reasonably anticipated.
A protective order is entered pursuant to Federal Rule of Civil Procedure 26(c) to govern the production of confidential materials.
Documents marked Confidential or Highly Confidential Attorneys Eyes Only are subject to the protective order.
The settlement agreement is filed under seal pending Court approval.
The Court approves the proposed class settlement as fair, reasonable, and adequate under Federal Rule of Civil Procedure 23(e).
Notice to the class was disseminated in compliance with Federal Rule of Civil Procedure 23(c)(2)(B).
Class members have the right to opt out of the settlement by the deadline specified in the notice.
Attorneys' fees are awarded as a percentage of the common fund pursuant to Boeing v. Van Gemert.
The lodestar cross-check applying reasonable hourly rates and hours expended supports the percentage fee award.
Pursuant to the Securities Exchange Act of 1934 Section 10(b) and Rule 10b-5, defendants are alleged to have made material misrepresentations.
The complaint pleads scienter with particularity as required by the Private Securities Litigation Reform Act of 1995.
Loss causation is adequately pled under Dura Pharmaceuticals Inc. v. Broudo.
Plaintiff alleges market manipulation under Section 9 of the Securities Exchange Act.
The Court grants the motion to compel arbitration pursuant to the Federal Arbitration Act 9 U.S.C. Section 1 et seq.
The arbitration clause is enforceable as a matter of federal law preempting state law.
The class action waiver in the arbitration agreement is enforceable under AT&T Mobility v. Concepcion.
Defendant's bankruptcy filing under Chapter 11 of the Bankruptcy Code triggers the automatic stay under 11 U.S.C. Section 362.
The plan of reorganization confirmed pursuant to 11 U.S.C. Section 1129 binds all creditors.
Equitable estoppel and quasi-estoppel principles are addressed in the bankruptcy proceedings.
"""

CORPUS_FINTECH = """
The Securities and Exchange Commission requires public companies to file Form 10-K annual reports pursuant to Section 13(a) of the Securities Exchange Act of 1934.
Quarterly Form 10-Q reports are filed within forty-five days following each fiscal quarter end.
Material events triggering Form 8-K disclosure obligations include changes in directors, officers, or auditors and entry into material definitive agreements.
The proxy statement on Schedule 14A discloses executive compensation pursuant to Item 402 of Regulation S-K.
The compensation discussion and analysis describes the company's compensation philosophy and practices.
The audit committee report addresses oversight of the independent registered public accounting firm.
Internal control over financial reporting is assessed pursuant to Section 404 of the Sarbanes-Oxley Act of 2002.
The auditor's report on internal controls is required for accelerated filers and large accelerated filers.
Material weaknesses in internal control over financial reporting must be disclosed in management's assessment.
Significant deficiencies are reported to the audit committee but not required for public disclosure.
The financial statements present fairly, in all material respects, the consolidated financial position of the Company.
Revenue recognition follows ASC 606 Revenue from Contracts with Customers under U.S. GAAP.
The five-step model identifies the contract, performance obligations, transaction price, allocates the transaction price, and recognizes revenue.
Performance obligations are satisfied either at a point in time or over time depending on the transfer of control.
Variable consideration is estimated using either the expected value method or the most likely amount method.
The constraint on variable consideration limits the amount included in the transaction price.
Lease accounting is governed by ASC 842, which requires lessees to recognize right-of-use assets and lease liabilities on the balance sheet.
Operating leases and finance leases are distinguished by criteria including ownership transfer and lease term relative to economic life.
Goodwill is tested for impairment annually pursuant to ASC 350 Intangibles - Goodwill and Other.
Triggering events between annual tests require interim impairment testing.
The qualitative assessment may avoid the need for the quantitative impairment test.
Long-lived asset impairment under ASC 360 is recognized when the carrying amount exceeds the undiscounted future cash flows.
Fair value measurements under ASC 820 follow the three-level hierarchy: Level 1 quoted prices, Level 2 observable inputs, Level 3 unobservable inputs.
Derivative instruments are accounted for under ASC 815, with fair value or hedge accounting depending on classification.
Cash flow hedges defer changes in fair value to other comprehensive income until the hedged transaction affects earnings.
Fair value hedges recognize changes in fair value of both the hedge and the hedged item in current period earnings.
Income taxes follow ASC 740, including the more-likely-than-not recognition threshold for uncertain tax positions.
Deferred tax assets and liabilities are recognized for temporary differences and operating loss carryforwards.
Valuation allowances reduce deferred tax assets to the amount more likely than not to be realized.
Stock-based compensation is recognized at fair value pursuant to ASC 718.
The Black-Scholes-Merton model and Monte Carlo simulation are common valuation approaches for stock options.
Restricted stock units are valued based on the grant-date fair value of the underlying stock.
Earnings per share is computed pursuant to ASC 260 with both basic and diluted EPS presented.
Dilutive securities including stock options, restricted stock units, and convertible debt are included in diluted EPS using the treasury stock method or if-converted method.
Segment reporting follows ASC 280, requiring disclosure of operating segments based on the management approach.
The chief operating decision maker reviews segment financial information for resource allocation and performance assessment.
The Federal Reserve Board sets monetary policy through the Federal Open Market Committee.
The federal funds target rate range is the primary tool of monetary policy.
Quantitative easing involves large-scale asset purchases by the Federal Reserve System.
The discount window provides short-term liquidity to depository institutions.
Reserve requirements were eliminated in March 2020 as part of pandemic response.
The Comprehensive Capital Analysis and Review evaluates capital adequacy of large bank holding companies.
The Dodd-Frank Wall Street Reform and Consumer Protection Act introduced enhanced prudential standards.
The Volcker Rule restricts proprietary trading and certain hedge fund and private equity activities.
The Volcker Rule is codified in Section 13 of the Bank Holding Company Act and 12 CFR Part 248.
The Bank Secrecy Act of 1970 imposes anti-money laundering requirements on financial institutions.
The USA PATRIOT Act of 2001 expanded BSA requirements with customer identification programs.
Suspicious activity reports are filed with the Financial Crimes Enforcement Network within thirty days of detection.
Currency transaction reports are required for cash transactions exceeding ten thousand dollars.
Customer due diligence rules require beneficial ownership identification at account opening.
Enhanced due diligence is required for foreign correspondent accounts and politically exposed persons.
Office of Foreign Assets Control sanctions screening is required for all financial transactions.
The Specially Designated Nationals list is updated regularly with sanctioned parties.
Anti-money laundering compliance programs include policies, procedures, internal controls, designated compliance officer, training, and independent testing.
The Federal Financial Institutions Examination Council issues guidance on bank examinations and ratings.
The CAMELS rating system evaluates capital adequacy, asset quality, management, earnings, liquidity, and sensitivity to market risk.
The Community Reinvestment Act of 1977 evaluates banks on meeting community credit needs.
The Equal Credit Opportunity Act prohibits discrimination in credit transactions.
The Truth in Lending Act requires disclosure of credit terms in consumer credit transactions.
The Real Estate Settlement Procedures Act governs disclosures and prohibited practices in real estate transactions.
The Fair Credit Reporting Act regulates consumer reporting agencies and creditor information furnishing.
The Gramm-Leach-Bliley Act establishes privacy and information security requirements for financial institutions.
The Investment Advisers Act of 1940 regulates investment advisers and imposes fiduciary duties on registered advisers.
Form ADV provides public disclosure of investment adviser business practices and conflicts of interest.
The Investment Company Act of 1940 regulates mutual funds, exchange-traded funds, and other registered investment companies.
The Securities Act of 1933 requires registration of securities offered to the public unless an exemption applies.
Regulation D provides exemptions for private placements to accredited investors and limited public offerings.
Rule 144 governs the resale of restricted and control securities.
Regulation A provides a streamlined registration option for offerings up to seventy-five million dollars.
The Jumpstart Our Business Startups Act of 2012 created emerging growth company status with reduced disclosure requirements.
Initial public offerings follow the registration process under the Securities Act with prospectus disclosure.
Emerging growth companies may follow scaled-down disclosure under JOBS Act provisions.
The Foreign Corrupt Practices Act prohibits payments to foreign officials to obtain or retain business.
The internal accounting controls provision requires accurate books and records and adequate internal controls.
The bribery and books and records provisions apply to issuers and domestic concerns.
The Office of the Comptroller of the Currency supervises national banks and federal savings associations.
The Federal Deposit Insurance Corporation provides deposit insurance up to two hundred fifty thousand dollars per depositor per insured bank per ownership category.
The National Credit Union Administration regulates federal credit unions and provides share insurance through the National Credit Union Share Insurance Fund.
The Consumer Financial Protection Bureau enforces federal consumer financial laws.
The European Central Bank sets monetary policy for the euro area through the Governing Council.
The Single Supervisory Mechanism conducts banking supervision in the euro area.
The European Banking Authority issues regulatory technical standards under the European supervisory framework.
The Capital Requirements Regulation and Capital Requirements Directive implement Basel III in the European Union.
Common Equity Tier 1 capital ratio requirements include minimum and capital conservation buffer.
The countercyclical capital buffer adjusts capital requirements based on credit cycle conditions.
The leverage ratio constrains balance sheet expansion regardless of risk weighting.
The liquidity coverage ratio ensures adequate high-quality liquid assets to cover thirty-day net cash outflows.
The net stable funding ratio promotes longer-term funding stability.
Markets in Financial Instruments Directive regulates investment services and activities in the European Union.
The Markets in Financial Instruments Regulation introduces transparency and reporting requirements.
The General Data Protection Regulation imposes data protection requirements with potential fines up to four percent of annual global turnover.
The Payment Services Directive governs payment services and electronic money in the European Union.
"""


# ─────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────


SEED_CORPORA: dict[str, str] = {
    "medical": CORPUS_MEDICAL,
    "legal": CORPUS_LEGAL,
    "fintech": CORPUS_FINTECH,
}


def _train_seed(vertical: str, target_vocab: int, out_dir: Path) -> Path:
    text = SEED_CORPORA[vertical]
    vocab = train_bpe(text, target_vocab_size=target_vocab)
    blob = serialise(vocab)
    out_path = out_dir / f"merges_{vertical}_v1_seed.bin"
    out_path.write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()[:16]
    print(
        f"wrote {out_path} ({len(blob):,} bytes; vocab_size={len(vocab)}; "
        f"sha256-prefix={digest})"
    )
    return out_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Train BPE merges for axon-csys-enterprise vertical encoders. "
            "Default mode emits the v1 seed encoders bundled with the crate; "
            "--corpus mode retrains on adopter data."
        )
    )
    parser.add_argument(
        "--vertical",
        choices=["medical", "legal", "fintech", "all"],
        default="all",
        help="Which vertical encoder to train. Default: all three.",
    )
    parser.add_argument(
        "--target-vocab",
        type=int,
        default=2048,
        help=(
            "Target vocab size (≥256). v1 seed corpora produce useful "
            "encoders at 1500-2500. Production retrain typically targets "
            "32000-50000 on full corpora. Default: 2048."
        ),
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help=(
            "Path to UTF-8 text file for adopter retrain. When set, "
            "--vertical names the output suffix (does NOT pull from "
            "the curated seed corpus)."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).parent.parent / "c-src" / "tokens",
        help="Output directory for merges_<vertical>_v1_seed.bin.",
    )
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.corpus is not None:
        # Adopter retrain mode.
        if args.vertical == "all":
            parser.error("--corpus requires --vertical to be one of medical|legal|fintech")
        text = args.corpus.read_text(encoding="utf-8")
        vocab = train_bpe(text, target_vocab_size=args.target_vocab)
        blob = serialise(vocab)
        corpus_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        out_path = args.out_dir / f"merges_{args.vertical}_retrain_{corpus_digest}.bin"
        out_path.write_bytes(blob)
        print(
            f"wrote {out_path} ({len(blob):,} bytes; vocab_size={len(vocab)}; "
            f"corpus_sha256-prefix={corpus_digest})"
        )
        return 0

    # Seed retrain mode.
    verticals = ["medical", "legal", "fintech"] if args.vertical == "all" else [args.vertical]
    for v in verticals:
        _train_seed(v, args.target_vocab, args.out_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
