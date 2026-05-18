# Procedure Code Keywords (v2)

Curated, comma-separated, lowercase phrases per CPT/HCPCS code. Designed to
live in a new `codes.keywords TEXT` column so the agent's existing
`_and_keyword_like` LIKE-match can hit lay terminology that nobody types
into official descriptions.

## Why this is curated, not data-derived

Spot-checked CPT 73721 against actual hospital descriptions in our DB:

| Description | Count |
|---|---|
| outpatient radiology | 59 |
| mri | 36 |
| mri jnt of lwr extre w/o dye | 24 |
| mri scan of leg joint without contrast | 22 |
| magnetic resonance imaging, any joint of lower extremity… | 17 |

**Not one description contains the word "knee"** — even though that's the #1
consumer search for this code. Hospitals write to the CPT short descriptor,
which strips body part specificity. So we can't lean on the existing
`hospital_code_charges.description` text and we can't lean on
`official_description` either; the lay vocabulary has to come from outside.

## Format conventions

- `keywords` is `TEXT NULL`, **lowercase**, **comma-separated phrases**, no
  spaces around commas
- Each phrase is something a real person types. "knee mri" beats "knee
  magnetic resonance imaging" beats "MRI of the lower extremity joint"
- Include both word orders ("knee mri" + "mri knee") — cheap, doubles match rate
- For codes covering multiple body parts (73721 = any lower-extremity joint),
  list each body part variant: "knee mri", "hip mri", "ankle mri", "foot mri"
- Brand names where they dominate the colloquial vocabulary: "ozempic",
  "wegovy", "botox", "lasik"
- **Source verified via WebFetch** for CPT 73721 (any lower-extremity joint,
  per AAPC). Other multi-joint codes follow the same pattern.

---

## Imaging — MRI

| Code | Real meaning | Keywords (comma-separated phrases) |
|---|---|---|
| CPT:70551 | MRI brain w/o contrast | brain mri,mri brain,head mri,mri head,brain scan,mri of the head,mri of the brain |
| CPT:70553 | MRI brain w & w/o contrast | brain mri with contrast,mri brain with contrast,brain mri contrast,head mri with contrast |
| CPT:73721 | MRI **any lower-extremity joint** w/o contrast (knee, hip, ankle, foot) | knee mri,mri knee,mri of the knee,knee scan,hip mri,mri hip,mri of the hip,ankle mri,mri ankle,foot mri,mri foot,mri of the lower extremity joint,lower extremity joint mri |
| CPT:73722 | MRI lower-extremity joint w/ contrast | knee mri with contrast,mri knee with contrast,hip mri with contrast,mri hip contrast,mri lower extremity joint with contrast |
| CPT:73221 | MRI **any upper-extremity joint** w/o contrast (shoulder, elbow, wrist) | shoulder mri,mri shoulder,mri of the shoulder,elbow mri,mri elbow,wrist mri,mri wrist,upper extremity joint mri,mri of the upper extremity joint |
| CPT:72148 | MRI lumbar spine w/o contrast | lumbar mri,lower back mri,back mri,mri lower back,mri lumbar,mri of the lumbar spine,mri of the lower back,lumbar spine mri |
| CPT:72141 | MRI cervical spine w/o contrast | neck mri,cervical mri,mri neck,mri cervical,mri of the cervical spine,mri of the neck,cervical spine mri |
| CPT:72146 | MRI thoracic spine w/o contrast | thoracic mri,mid-back mri,mri thoracic spine,mri mid back,thoracic spine mri |
| CPT:74181 | MRI abdomen w/o contrast | abdomen mri,abdominal mri,mri abdomen,mri stomach,stomach mri,belly mri,mri belly |
| CPT:74183 | MRI abdomen w & w/o contrast | abdomen mri with contrast,abdominal mri with contrast,mri abdomen contrast |
| CPT:72195 | MRI pelvis w/o contrast | pelvis mri,pelvic mri,mri pelvis,mri pelvic,mri of the pelvis |

## Imaging — CT

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:70450 | CT head/brain w/o contrast | head ct,ct head,brain ct,ct brain,ct scan head,ct of the head,head cat scan,brain cat scan |
| CPT:70460 | CT head/brain w/ contrast | head ct with contrast,brain ct with contrast,ct brain contrast |
| CPT:71250 | CT chest w/o contrast | chest ct,ct chest,lung ct,ct lung,ct scan chest,chest cat scan,ct of the chest |
| CPT:71260 | CT chest w/ contrast | chest ct with contrast,ct chest contrast,lung ct with contrast |
| CPT:74176 | CT abdomen & pelvis w/o contrast | abdominal ct,ct abdomen,abdomen ct,ct of the abdomen,belly ct,ct belly,ct abdomen pelvis,abdomen and pelvis ct,ct scan abdomen |
| CPT:74177 | CT abdomen & pelvis w/ contrast | abdominal ct with contrast,ct abdomen contrast,ct abdomen and pelvis with contrast |
| CPT:70498 | CT angiography neck | neck ct angiogram,carotid cta,ct angio neck |
| CPT:74160 | CT abdomen w/ contrast | abdomen ct contrast,abdominal ct with contrast |

## Imaging — X-ray & Ultrasound

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:71045 | Chest X-ray, single view | chest x-ray,chest xray,chest radiograph,lung x-ray,one view chest x-ray |
| CPT:71046 | Chest X-ray, 2 views | chest x-ray,chest xray,2 view chest x-ray,two view chest x-ray |
| CPT:73564 | Knee X-ray, 4+ views | knee x-ray,knee xray,knee radiograph,x-ray knee |
| CPT:72100 | X-ray lumbar spine 2-3 views | lower back x-ray,lumbar x-ray,back x-ray,lumbar spine x-ray |
| CPT:76700 | Abdominal ultrasound, complete | abdominal ultrasound,abdomen ultrasound,belly ultrasound,sonogram abdomen,ultrasound abdomen |
| CPT:76830 | Transvaginal ultrasound | transvaginal ultrasound,pelvic ultrasound,vaginal ultrasound,internal ultrasound |
| CPT:76805 | Pregnancy ultrasound, 2nd/3rd trimester | pregnancy ultrasound,prenatal ultrasound,baby ultrasound,fetal ultrasound,ob ultrasound,obstetric ultrasound |
| CPT:76770 | Ultrasound retroperitoneal | kidney ultrasound,renal ultrasound,retroperitoneal ultrasound |

## Office visits & preventive care

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:99213 | Office visit, established patient, 20-29 min | doctor visit,office visit,follow up,follow-up visit,checkup,established patient visit,routine doctor visit |
| CPT:99214 | Office visit, established patient, 30-39 min | doctor visit,office visit,longer office visit,checkup,detailed office visit,extended doctor visit |
| CPT:99203 | New patient office visit, 30-44 min | new patient visit,first doctor visit,new doctor visit,intake visit |
| CPT:99204 | New patient office visit, 45-59 min | new patient visit,first doctor visit,extended new patient visit |
| CPT:99396 | Preventive visit, established, age 40-64 | annual checkup,annual physical,yearly checkup,physical,preventive visit,wellness visit,annual exam,routine physical |
| CPT:99397 | Preventive visit, established, age 65+ | annual checkup,annual physical,physical,senior physical,medicare annual wellness,welcome to medicare visit |
| CPT:99386 | Preventive visit, new, age 40-64 | annual checkup,annual physical,new patient physical,physical exam,wellness visit |
| HCPCS:G0438 | Medicare initial Annual Wellness Visit | medicare wellness visit,annual wellness visit,medicare awv,initial wellness visit |
| HCPCS:G0439 | Medicare subsequent Annual Wellness Visit | annual wellness visit,medicare wellness,awv,subsequent wellness visit |

## Emergency & urgent care

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:99281 | ER visit, level 1 (minor) | er visit,emergency room,emergency visit,minor er visit,low-level er |
| CPT:99282 | ER visit, level 2 | er visit,emergency room visit,emergency room,routine er |
| CPT:99283 | ER visit, level 3 (moderate) | er visit,emergency room visit,emergency room,mid-level er |
| CPT:99284 | ER visit, level 4 (high) | er visit,emergency room,serious er visit,emergency room visit,high-level er |
| CPT:99285 | ER visit, level 5 (highest, critical) | er visit,emergency room,severe er visit,critical er,critical care er,life-threatening emergency |
| CPT:99291 | Critical care first 30-74 min | critical care,icu care,intensive care visit |

## Mental health & therapy

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:90791 | Psychiatric diagnostic eval (no medical) | therapy intake,first therapy session,psych evaluation,mental health evaluation,psychiatric assessment,new patient therapy |
| CPT:90792 | Psychiatric diagnostic eval (with medical) | psychiatric intake with medical,psychiatric evaluation with medical,first psychiatry visit |
| CPT:90834 | Psychotherapy, 38-52 min | therapy session,therapy,counseling,psychotherapy,mental health session,therapist visit,45 minute therapy |
| CPT:90837 | Psychotherapy, 53+ min | therapy session,therapy,long therapy session,counseling,psychotherapy hour,60 minute therapy,extended therapy |
| CPT:90832 | Psychotherapy, 16-37 min | therapy,short therapy session,brief counseling,brief therapy,30 minute therapy |
| CPT:90847 | Family psychotherapy (with patient) | family therapy,couples therapy,family counseling,couples counseling |

## Common surgeries

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:27447 | Total knee arthroplasty | knee replacement,total knee replacement,knee surgery,tkr,new knee,total knee arthroplasty,knee joint replacement |
| CPT:27130 | Total hip arthroplasty | hip replacement,total hip replacement,hip surgery,thr,new hip,total hip arthroplasty,hip joint replacement |
| CPT:66984 | Cataract surgery w/ IOL implant | cataract surgery,cataract removal,lens replacement,eye surgery cataract,cataracts,iol surgery,intraocular lens surgery |
| CPT:47562 | Laparoscopic cholecystectomy | gallbladder surgery,gallbladder removal,cholecystectomy,gall bladder surgery,gallbladder removed,laparoscopic gallbladder |
| CPT:44950 | Appendectomy (open) | appendix surgery,appendectomy,appendix removal,burst appendix surgery |
| CPT:44970 | Laparoscopic appendectomy | laparoscopic appendectomy,laparoscopic appendix removal,appendix surgery laparoscopic |
| CPT:49505 | Inguinal hernia repair, open | hernia surgery,hernia repair,inguinal hernia,groin hernia |
| CPT:49585 | Umbilical hernia repair | umbilical hernia surgery,belly button hernia,umbilical hernia |
| CPT:42820 | Tonsillectomy & adenoidectomy, under age 12 | tonsil removal,tonsillectomy,tonsils out,adenoid surgery,tonsils and adenoids,kids tonsil surgery |
| CPT:42821 | Tonsillectomy & adenoidectomy, age 12+ | tonsil removal,tonsillectomy,adult tonsil removal,tonsils and adenoids |
| CPT:55250 | Vasectomy | vasectomy,male sterilization,getting snipped,vasectomy procedure |
| CPT:58300 | IUD insertion | iud,iud insertion,birth control iud,intrauterine device |
| CPT:58301 | IUD removal | iud removal,remove iud,birth control removal |
| CPT:59400 | Vaginal delivery, global package | childbirth,vaginal delivery,natural birth,having a baby,delivery,labor and delivery |
| CPT:59510 | Cesarean delivery, global package | c-section,cesarean,cesarean section,csection,c section,cesarean delivery |
| CPT:59514 | Cesarean delivery only (not global) | c-section delivery only,cesarean only |

## Screening & diagnostic

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:77067 | Screening mammography, bilateral | mammogram,breast screening,mammography,breast cancer screening,annual mammogram,screening mammogram |
| CPT:77065 | Diagnostic mammography, unilateral | diagnostic mammogram,unilateral mammogram,mammogram one side |
| CPT:77066 | Diagnostic mammography, bilateral | diagnostic mammogram,bilateral diagnostic mammogram,full mammogram |
| CPT:45378 | Diagnostic colonoscopy | colonoscopy,colon screening,colon scope,gi scope,colonoscopy procedure |
| CPT:45380 | Colonoscopy w/ biopsy | colonoscopy with biopsy,colon biopsy,colonoscopy biopsy |
| CPT:45385 | Colonoscopy w/ polyp removal | colonoscopy with polyp removal,colon polyp,polyp removal,colonoscopy polyp |
| HCPCS:G0121 | Screening colonoscopy, average-risk | screening colonoscopy,routine colonoscopy,preventive colonoscopy |
| CPT:95810 | Sleep study, polysomnography (attended) | sleep study,polysomnography,sleep apnea test,overnight sleep test,sleep test |
| CPT:95806 | Sleep study, home unattended | home sleep study,at-home sleep test,home sleep apnea test |
| CPT:93000 | EKG, complete | ekg,ecg,electrocardiogram,heart test ekg,routine ekg |
| CPT:93306 | Echocardiogram, complete | echocardiogram,echo,heart ultrasound,cardiac ultrasound,echo cardiogram |
| CPT:93015 | Stress test, cardiovascular | stress test,cardiac stress test,treadmill test,exercise stress test,heart stress test |
| CPT:95004 | Allergy testing, skin scratch | allergy test,allergy testing,skin allergy test,scratch test |
| CPT:88141 | Pap smear interpretation | pap smear,pap test,cervical screening,pap |
| CPT:81025 | Pregnancy test, urine | pregnancy test,urine pregnancy test,upt |

## Lab panels

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:80053 | Comprehensive metabolic panel (CMP) | metabolic panel,cmp,blood test panel,metabolic blood test,comprehensive metabolic panel |
| CPT:80048 | Basic metabolic panel (BMP) | basic metabolic panel,bmp,basic blood panel |
| CPT:85025 | Complete blood count w/ differential | cbc,complete blood count,blood count test,blood panel,cbc with differential |
| CPT:80061 | Lipid panel | lipid panel,cholesterol test,cholesterol panel,lipids blood test,lipids |
| CPT:83036 | Hemoglobin A1c | a1c,hba1c,diabetes test,hemoglobin a1c,blood sugar test,glycohemoglobin |
| CPT:84443 | TSH | tsh,thyroid test,thyroid stimulating hormone,thyroid panel |
| CPT:84439 | Free T4 | t4,thyroxine,free t4,thyroid t4 |
| CPT:81001 | Urinalysis, complete w/ microscopy | urinalysis,urine test,urine analysis,ua |
| CPT:87491 | Chlamydia detection | chlamydia test,std test chlamydia,chlamydia screening |
| CPT:87591 | Gonorrhea detection | gonorrhea test,std test gonorrhea,gonorrhea screening |

## Vaccines

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:90686 | Flu shot, quadrivalent (4-strain), IM | flu shot,flu vaccine,influenza vaccine,annual flu shot,quad flu shot |
| CPT:90471 | Vaccine administration, first injection | vaccine,vaccination,immunization,shot,immunization shot |
| CPT:90715 | Tdap vaccine, age 7+ | tdap,tetanus shot,tetanus diphtheria pertussis,booster shot |
| CPT:90734 | Meningococcal vaccine | meningococcal vaccine,meningitis shot,meningitis vaccine |

## Drugs (J-codes)

**Reliability warning:** Hospital MRFs cover drugs *administered in the
facility* (IV, in-clinic injections, OR meds). Self-injected drugs that are
pharmacy-dispensed (Ozempic, Wegovy, insulin pens, oral pills) often **don't
appear** in hospital MRFs at all — they're billed via pharmacy benefits, not
the chargemaster. Keep these entries so the keyword search resolves to a
code, but expect the agent to often report "no hospital pricing data".

| Code | Real meaning | Keywords | Notes |
|---|---|---|---|
| HCPCS:J0585 | Botulinum toxin A (Botox) per unit | botox,botulinum toxin,botox injection,wrinkle injection,cosmetic botox,therapeutic botox | Better hit rate than self-injectables; hospital-administered for migraine, spasticity, cosmetic |
| HCPCS:J3490 | Unclassified drug injection (catch-all) | ozempic,semaglutide,wegovy,glp-1,weight loss injection,unclassified injection | Mostly pharmacy-dispensed; MRF hits are rare |
| HCPCS:J1815 | Insulin (per 5 units) | insulin,insulin injection | Pharmacy-dispensed; rare in hospital MRFs |
| HCPCS:J7325 | Hyaluronic acid knee injection (Synvisc/Euflexxa) | knee injection,hyaluronic acid,knee gel injection,synvisc,euflexxa,viscosupplementation | Hospital-administered, decent hit rate |
| HCPCS:J9173 | Durvalumab (Imfinzi) per 10 mg | durvalumab,imfinzi,immunotherapy,cancer immunotherapy | Hospital-administered chemo, good hit rate |
| HCPCS:J9035 | Bevacizumab (Avastin) per 10 mg | avastin,bevacizumab,chemo,cancer drug | Hospital chemo, good hit rate |

## Vision & hearing

LASIK and most refractive surgery is performed at outpatient eye centers,
not hospitals — included for completeness but **expect low hit rate** in
hospital MRFs.

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:65760 | Keratomileusis (LASIK-adjacent) | lasik,laser eye surgery,vision correction surgery,refractive surgery |
| CPT:92014 | Comprehensive eye exam, established | eye exam,vision exam,annual eye exam,ophthalmologist visit,routine eye exam |
| CPT:92004 | Comprehensive eye exam, new patient | new patient eye exam,first eye exam,new ophthalmologist visit |
| CPT:92557 | Hearing test, comprehensive audiometry | hearing test,audiogram,hearing exam,audiology test,full hearing test |

## Procedural — gastro, ortho, derm, ENT

| Code | Real meaning | Keywords |
|---|---|---|
| CPT:43239 | Upper endoscopy w/ biopsy (EGD) | endoscopy,egd,upper endoscopy,gastroscopy,upper gi scope,stomach scope |
| CPT:43235 | Upper endoscopy, diagnostic | diagnostic endoscopy,egd diagnostic,upper gi endoscopy |
| CPT:11102 | Skin biopsy, tangential | skin biopsy,mole biopsy,dermatology biopsy,shave biopsy |
| CPT:17110 | Wart removal, up to 14 lesions | wart removal,wart treatment,cryotherapy wart |
| CPT:69210 | Ear wax removal, one or both ears | earwax removal,ear cleaning,cerumen removal |

---

## Stage 2 plan (post-hackathon)

For the long tail (the other ~2.6M codes — mostly hospital-specific CDM
items like "SUP-15000 STAPLER, SKIN" that nobody Googles), the right
approach is a one-shot Gemini Flash batch over the top ~10k codes by
`hospital_code_charges` row count. Prompt the model with:

- The code (e.g. "CPT:73721")
- The most common hospital description
- The official descriptor where known
- Ask it to generate 5-10 comma-separated lay-person search phrases

At Flash pricing, 10k codes ≈ $0.30 total. Then a manual sanity-pass on the
output (probably worth spending 1-2 hours catching obvious misses).

For now, this curated set covers the procedures the demo prompts actually
touch, plus the common procedure-shopping universe.

## Next steps in this repo

1. **Add the column** (via cloud-sql-proxy):
   ```sql
   ALTER TABLE codes ADD COLUMN keywords TEXT NULL
     COMMENT 'Comma-separated lowercase consumer-search aliases; LIKE-matched by find_procedure';
   ```
2. **Load the rows** — I can emit `UPDATE codes SET keywords = '...' WHERE code = '...'` statements for everything above. ~100 statements, runs in seconds.
3. **Wire `Code.keywords` into `_and_keyword_like`** in `apps/api/routers/agent.py` (one line in the `columns` list).
4. **Test** with the agent: try "knee mri" → should resolve to CPT:73721 cleanly.

Tell me when you've reviewed and I'll generate the SQL.
