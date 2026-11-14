# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**

  - Chủ đề: truy xuất văn bản pháp luật lao động. Corpus là **Bộ luật Lao động số 45/2019/QH14**, Quốc hội khóa XIV thông qua ngày 20/11/2019. Đây là nguyên văn khi ban hành, **không phải văn bản hợp nhất**: các sửa đổi theo VBHN 125/VBHN-VPQH (2025) và 18/VBHN-VPQH (2026) không có trong corpus.
  - Nguồn: file PDF đăng trên website trường ĐH Ngân hàng TP.HCM (`phongtochuc.hub.edu.vn`), truy cập ngày 2026-11-14, sha256 `d18ea87c…f7c7`. Đây không phải cổng chính thức, nên các Điều dùng trong benchmark cần đối chiếu với vbpl.vn hoặc thuvienphapluat.
  - Quyền sử dụng: văn bản quy phạm pháp luật không thuộc đối tượng bảo hộ quyền tác giả (khoản 1 Điều 15 Luật Sở hữu trí tuệ).
  - Số trang: PDF có **47 trang vật lý**, trong đó **46 trang có nội dung** (189.180 ký tự sau chuẩn hóa).
  - Quy tắc tính trang: đánh số trang PDF từ 1. Một trang được tính là có nội dung nếu sau chuẩn hóa còn ít nhất 200 ký tự. File không có bìa hay mục lục. Trang 47 bị loại vì chỉ chứa tên người ký (19 ký tự).
  - Chi tiết từng trang: [data/manifest.json](../../data/manifest.json).
- **Chuẩn hóa, lỗi và giới hạn:**

  - Trích văn bản bằng pypdf 6.21.4, theo từng trang. File PDF được chuyển từ Word nên có lớp chữ thật, không cần OCR.
  - Chuẩn hóa Unicode về dạng NFC; gộp khoảng trắng; bỏ các dòng phân cách `----`.
  - Ghép lại các dòng bị PDF ngắt giữa câu, kể cả khi câu bị ngắt qua trang. Dòng đầu Chương, Mục, Điều, khoản `1.` và điểm `a)` được giữ là đoạn riêng.
  - Kiểm tra cấu trúc: tách được 17/17 chương, 24 mục, 220 điều đánh số liên tục 1→220, không thiếu và không trùng. Log ở [starter/results/ingest_log.json](../../starter/results/ingest_log.json).
  - Lỗi ghi nhận: chỉ có trang 47 bị loại vì quá ngắn. Không có trang rỗng, không có lỗi trích xuất.
  - Giới hạn:
    - Đoạn chữ ký ("CHỦ TỊCH QUỐC HỘI") bị gộp vào chunk của Điều 220.
    - Số trang là trang của file PDF này, không phải trang Công báo.
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:**

  - Embedding: `intfloat/multilingual-e5-small` (revision `614241f6`), chạy local bằng sentence-transformers 5.7.0 / torch 2.15.0 trên **CPU**. Không dùng MPS vì torch MPS bị crash trên macOS 14.5.

    - Vector **384 chiều**, chuẩn hóa L2.
    - Tiền tố `passage: ` cho tài liệu và `query: ` cho câu hỏi.
    - max_seq_length là 512 token; chunk B dài nhất là 399 token, nên không chunk nào bị cắt.
  - Vector store: PostgreSQL 16 + pgvector (image `pgvector/pgvector:0.8.7-pg16`), chạy bằng Docker qua Colima. Client là psycopg 3.3.8 và pgvector-python 0.4.2.

    - Metric: cosine (`<=>`), score = 1 − distance.
    - Tìm kiếm **exact** (quét tuần tự, không dùng index ANN).
  - Lệnh chạy (trong `starter/`): `python -m src.prepare` → `python -m src.index` → `python -m src.run` (dev) → `python -m src.run --split test`.
  - Chi phí: **0 USD**, vì không gọi API nào.
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**

  - Bắt buộc: `document_id`, `source` (đường dẫn file), `page` (trang bắt đầu chunk) và `pages` (mọi trang chunk chạm tới).
  - Bổ sung:
    - `chapter` (số La Mã I–XVII), là **trường dùng để lọc**.
    - `chapter_title`, `section` (Mục), `articles` (danh sách Điều), `content_hash`.
  - Nguồn giá trị: lấy trực tiếp từ các dòng "Chương X", "Mục n." và "Điều n." trong văn bản. Không có giá trị nào do tự suy đoán.
  - Lý do chọn `chapter`: mỗi chương là một phạm vi chủ đề rõ ràng (hợp đồng, thời giờ làm việc, lao động nữ, chưa thành niên, kỷ luật, tranh chấp…). Nhiều quy định giống nhau nằm ở các chương khác nhau, ví dụ thời hiệu kỷ luật (Chương VIII) và thời hiệu tranh chấp (Chương XIV).

## Cấu hình và benchmark

- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**
  - **A:** chunk kích thước cố định **500 ký tự, overlap 50**, cắt trên toàn văn bản (bỏ qua cấu trúc), không lọc. Kết quả: **421 chunk**, trung vị 500 ký tự; 60 chunk nằm vắt qua 2 trang, 18 chunk vắt qua 2 chương.
  - **B:** **mỗi Điều một chunk**, tối đa **1.500 ký tự**. Điều nào dài hơn thì tách theo khoản/điểm, và mỗi phần lặp lại tiêu đề Điều kèm chữ "(tiếp theo)". Không lọc. Kết quả: **252 chunk**, trung vị 688 ký tự, dài nhất 1.486 ký tự; không chunk nào vắt qua 2 chương.
  - **C:** dùng **cùng các dòng dữ liệu của B** (cùng chunk, cùng vector). Điểm khác duy nhất: **thêm lọc `chapter = X` trong SQL khi câu hỏi có filter**. Câu không có filter thì C cho kết quả giống hệt B.
  - Nguyên tắc so sánh có kiểm soát: A–B chỉ khác cách chunk; B–C chỉ khác filter. Cả ba dùng cùng corpus, cùng model, cùng top-k = 3.
  - Thời gian đọc + chuẩn hóa: 3,09 giây. Chia chunk: 0,02 giây. Tạo embedding và nạp vào database: A 11,1 giây, B 9,4 giây (CPU).
  - Nạp lại cùng phiên bản: lần 2 bỏ qua cả 421 + 252 chunk vì `content_hash` không đổi, 0 dòng trùng, mỗi cấu hình mất khoảng 0,08 giây ([index_log.json](../../starter/results/index_log.json)). Khi tài liệu thay đổi: chunk có hash mới được tạo embedding lại và upsert; chunk không còn tồn tại bị xóa.
- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - 20 câu: **15 dev và 5 test**, xem [benchmark/questions.jsonl](../../benchmark/questions.jsonl).
  - Phân loại: 5 câu trực tiếp, 6 câu có điều kiện, 4 câu diễn đạt lại, 1 câu ngoại lệ, 4 câu có metadata filter.
  - Câu có filter: q12 (X), q13 (XI), q14 (VIII) thuộc dev; q20 (XIV) thuộc test. Giá trị filter lấy từ phạm vi người hỏi đã nêu trong câu, ví dụ "trong phần kỷ luật lao động". Mỗi câu có một Điều dễ gây nhầm ở chương khác.
  - Chia dev/test **theo Điều**: test dùng các Điều 46, 115, 128, 139, 190, không câu dev nào dùng các Điều này. Nguy cơ rò rỉ theo chủ đề đã ghi trong [benchmark/README.md](../../benchmark/README.md).
  - Kiểm chứng evidence: script `python -m src.check_benchmark` xác nhận cả 20 đoạn trích có trong văn bản (đã chuẩn hóa) của đúng trang `gold_page`.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:** chỉ dùng kết quả dev, theo thứ tự ưu tiên: (1) Evidence Hit@3 → (2) Hit@1 → (3) coherence trung bình → (4) tài nguyên (số chunk, thời gian). Sau khi cố định cấu hình mới chạy test, và chỉ chạy **một lần**.
  - Sau dev, B và C hòa ở cả 4 tiêu chí. Tôi bổ sung quy tắc phá hòa **trước khi chạy test**: chọn cấu hình có filter, vì nó không làm giảm chỉ số dev nào và giới hạn được phạm vi khi người dùng cung cấp trước. **Cấu hình chọn: C** (ghi trong [benchmark/README.md](../../benchmark/README.md)).

## Kết quả

Test chỉ chạy một lần, sau khi đã chốt cấu hình. Top-k = 3. Thời gian là trung vị mỗi câu (embedding câu hỏi khoảng 23,5 ms, dùng chung cho cả 3 cấu hình, cộng thời gian truy vấn pgvector).

| Strategy | Split | Hit@1 (n/N)  | Evidence Hit@3 (n/N) | Chunk count              | Thời gian                     | Chi phí |
| -------- | ----- | ------------ | -------------------- | ------------------------ | ------------------------------ | -------- |
| A        | dev   | 9/15 = 0,60  | 14/15 = 0,93         | 421                      | 22,5 ms/truy vấn; nạp 11,1 s | 0        |
| B        | dev   | 14/15 = 0,93 | 15/15 = 1,00         | 252                      | 21,6 ms/truy vấn; nạp 9,4 s  | 0        |
| C        | dev   | 14/15 = 0,93 | 15/15 = 1,00         | 252 (dùng chung với B) | 20,7 ms/truy vấn              | 0        |
| A        | test  | 3/5 = 0,60   | 3/5 = 0,60           | 421                      | 22,8 ms/truy vấn              | 0        |
| B        | test  | 5/5 = 1,00   | 5/5 = 1,00           | 252                      | 21,2 ms/truy vấn              | 0        |
| C        | test  | 5/5 = 1,00   | 5/5 = 1,00           | 252                      | 20,8 ms/truy vấn              | 0        |

Evidence bị tách qua 2 chunk trong top-3: A có 5/15 câu dev và 2/5 câu test; B và C có 1/15 câu dev (q04: phần trùng một nửa nằm ở Điều 36, xem dưới) và 0/5 câu test.

| Strategy | Coherence trung bình /2 (n)                    | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
| -------- | ----------------------------------------------- | ------------------------------ | --------------------------------- | --------------------------------------------- |
| A        | 0,80 (n=10; 3 điểm 0, 6 điểm 1, 1 điểm 2) | 15/15                          | test 1/1, dev 3/3                 | 1 / 0 / 4, trung bình 1,60                   |
| B        | 2,00 (n=10; 10 điểm 2)                        | 15/15                          | test 1/1, dev 3/3                 | 0 / 0 / 5, trung bình 2,00                   |
| C        | 2,00 (n=10; dùng chung chunk với B)           | 15/15                          | test 1/1, dev 3/3                 | 0 / 0 / 5, trung bình 2,00                   |

Filter tuân thủ được đo ở cả A và B (không lọc) để so sánh: top-3 có nằm hết trong chương mà câu hỏi yêu cầu không.

Đường dẫn trace, nhãn thủ công và cách chọn mẫu:

- Trace: [traces_dev.jsonl](../../starter/results/traces_dev.jsonl), [traces_test.jsonl](../../starter/results/traces_test.jsonl). Chỉ số: [metrics_dev.json](../../starter/results/metrics_dev.json), [metrics_test.json](../../starter/results/metrics_test.json).
- Nhãn: [audit_coherence.csv](../../starter/results/audit_coherence.csv), [audit_metadata_test.csv](../../starter/results/audit_metadata_test.csv), [audit_grounding_test.csv](../../starter/results/audit_grounding_test.csv). Mỗi nhãn có lý do ở cột `reason` / `error_note`.
- Cách chọn mẫu coherence (chốt trước khi xem điểm): vị trí là **dòng đầu tiên của các trang PDF 2–11** (trang 1 bắt đầu bằng quốc hiệu). Với mỗi vị trí, chấm chunk của từng cấu hình chứa vị trí đó.

## Phân tích và kết luận

- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:**

  - **A–B (chỉ đổi cách chunk):** B tốt hơn ở mọi khía cạnh.
    - Hit@1 dev tăng từ 9/15 lên 14/15; Hit@3 test tăng từ 3/5 lên 5/5.
    - Coherence tăng từ 0,80 lên 2,00; grounding tăng từ 1,60 lên 2,00.
    - Số chunk ít hơn 40% (252 so với 421). Thời gian nạp và thời gian truy vấn tương đương.
    - Nguyên nhân chính: A cắt giữa câu và giữa khoản, nên evidence bị tách (5/15 câu dev) và chunk mất tiêu đề Điều (3 trong 10 mẫu coherence bị 0 điểm).
  - **B–C (chỉ thêm filter):** **không có khác biệt đo được**. Top-3 của C giống hệt B ở cả 20 câu. Lý do: cả 4 câu có filter (q12, q13, q14, q20) đều chứa từ khóa chủ đề rõ ("lao động nữ", "chưa thành niên", "kỷ luật", "tranh chấp"), nên tìm kiếm không lọc đã trả về top-3 đúng chương (filter tuân thủ 4/4 ngay cả ở B). Với corpus và kiểu câu hỏi này, filter chương chỉ đóng vai trò bảo hiểm, chưa có bằng chứng là nó cải thiện kết quả.
  - **Ví dụ sai 1 – test q18 với A** (Điều 139, trang 29): câu "…sinh đôi trở lên thì tính từ con thứ 02 trở đi, cứ mỗi con, người mẹ được nghỉ thêm 01 tháng" bị cắt giữa `A:0255` ("…nghỉ thêm 0") và `A:0256` ("ứ 02 trở đi…"). Overlap 50 ký tự không đủ chứa câu, nên không chunk nào chứa trọn evidence: Hit@3 = miss.
  - **Ví dụ sai 2 – test q16 với A** (Điều 46, trang 11): top-3 là `A:0093` và `A:0092` (khoản 2–3 của Điều 46, cộng Điều 47) và `A:0211` (Điều 113). Câu chứa mức "một nửa tháng tiền lương" nằm ở `A:0091` nhưng không lọt top-3. Tệ hơn, `A:0093` chứa câu của Điều 47 "cứ mỗi năm làm việc trả 01 tháng tiền lương", dễ dẫn tới trả lời sai: grounding = 0.
  - **Ví dụ lỗi của B – dev q04** (Điều 35, trang 8): top-1 là `B:art036:1`, tức Điều 36 về thời hạn báo trước của *người sử dụng lao động* ("Ít nhất 45 ngày đối với hợp đồng lao động không xác định thời hạn"), câu chữ gần giống Điều 35 về thời hạn của *người lao động*. Đáp án đúng ở hạng 2. Embedding không phân biệt tốt chủ thể của quy định.
- **Tính hữu dụng của metadata (ngoài việc đủ và đúng 45/45):**

  - `page`/`pages` và `articles` giúp **truy vết**. Mọi kết quả trong trace đều mở được đúng trang PDF và đúng Điều. Ví dụ, lỗi q18 của A xác định được ngay là câu bị cắt tại ranh giới giữa `A:0255` và `A:0256` trên trang 29. Với chunk A, `pages` = `[28, 29]` cho biết chunk vắt qua trang. 60/421 chunk A như vậy, nên nếu chỉ lưu `page` thì sẽ truy vết thiếu.
  - `chapter` giúp **lọc**. Trong lần chạy thử bằng một câu ngoài benchmark ("nghỉ bao nhiêu phút mỗi ngày"), lọc Chương X đã đổi top-1 từ Điều 109 (Chương VII) sang Điều 137 khoản 4.
  - Hạn chế:
    - Với A, `chapter` lấy theo đầu chunk, trong khi 18/421 chunk A vắt qua 2 chương. Lọc theo chương có thể giữ lại một chunk mà nửa sau thuộc chương khác.
    - `chapter` chỉ có ích khi người dùng biết trước phạm vi. Trên 4 câu có filter của benchmark, filter không thay đổi kết quả.
    - `year` là hằng số (cả corpus đều là 2019), nên không dùng để lọc được.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**

  - Chọn **C**: chunk theo Điều cộng filter chương khi người dùng cung cấp phạm vi.
  - Đánh đổi: chunk B dài hơn (trung vị 688 so với 500 ký tự, dài nhất 1.486), nên top-3 đưa vào ngữ cảnh nhiều chữ hơn. Ngoài ra, cách chunk này phụ thuộc vào việc nhận dạng đúng cấu trúc "Điều N." (ở đây là 220/220), nên chỉ áp dụng tốt cho văn bản có cấu trúc rõ như luật, nghị định.
  - Filter chương chỉ có ích khi người dùng biết và cung cấp phạm vi trước. Nếu nhập sai phạm vi, filter sẽ loại mất đáp án đúng; với bộ câu hỏi này, rủi ro đó chưa được kiểm tra.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**

  - Corpus chỉ có 1 tài liệu, là nguyên văn 2019 chưa hợp nhất các sửa đổi 2025–2026. File PDF lấy từ website trường đại học, không phải cổng chính thức.
  - Test chỉ có 5 câu, mỗi câu là 20% điểm. Kết quả 5/5 của B/C **không chứng minh** được chiến lược tốt nhất nói chung, và không suy rộng ra ngoài corpus này.
  - Thời gian đo trên 1 máy (CPU, Docker Desktop) ở một lần chạy, chưa lặp lại. Chi phí bằng 0 vì chạy local.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**

  - Thêm câu hỏi **không nêu tên chủ đề** (ví dụ "được nghỉ bao nhiêu phút mỗi ngày?" với filter Chương X), cùng câu có phạm vi sai, để đo đúng tác dụng và rủi ro của filter.
  - Thêm cấu hình A' (cố định 500 ký tự nhưng cắt theo ranh giới câu, hoặc overlap lớn hơn) để tách riêng ảnh hưởng của "cắt giữa câu" và "không theo Điều".
  - Mở rộng test lên 15–20 câu, và cho thêm một người chấm độc lập để đo độ đồng thuận.
  - Thử hybrid BM25 + dense, hoặc thêm tiêu đề Điều vào chunk, để xử lý lỗi nhầm chủ thể như q04.
  - Dùng bản hợp nhất 18/VBHN-VPQH (2026) để có câu trả lời theo luật hiện hành, và filter theo `version`.
