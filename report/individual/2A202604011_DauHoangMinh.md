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
  - Lúc đầu định dùng `BAAI/bge-m3`, nhưng không tải được: file 2,2 GB đứng ở khoảng 1 GB. Vì vậy đổi sang e5-small trước khi chạy bất kỳ thí nghiệm nào. Cả ba cấu hình dùng cùng một model.
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
  - Thời gian đọc + chuẩn hóa: 3,09 giây. Chia chunk: 0,02 giây.
- **≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:**
  - 20 câu: **15 dev và 5 test**, xem [benchmark/questions.jsonl](../../benchmark/questions.jsonl).
  - Phân loại: 5 câu trực tiếp, 6 câu có điều kiện, 4 câu diễn đạt lại, 1 câu ngoại lệ, 4 câu có metadata filter.
  - Câu có filter: q12 (X), q13 (XI), q14 (VIII) thuộc dev; q20 (XIV) thuộc test. Giá trị filter lấy từ phạm vi người hỏi đã nêu trong câu, ví dụ "trong phần kỷ luật lao động". Mỗi câu có một Điều dễ gây nhầm ở chương khác.
  - Chia dev/test **theo Điều**: test dùng các Điều 46, 115, 128, 139, 190, không câu dev nào dùng các Điều này. Nguy cơ rò rỉ theo chủ đề đã ghi trong [benchmark/README.md](../../benchmark/README.md).
  - Kiểm chứng evidence: script `python -m src.check_benchmark` xác nhận cả 20 đoạn trích có trong văn bản (đã chuẩn hóa) của đúng trang `gold_page`.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:** chỉ dùng kết quả dev, theo thứ tự ưu tiên: (1) Evidence Hit@3 → (2) Hit@1 → (3) coherence trung bình → (4) tài nguyên (số chunk, thời gian). Sau khi cố định cấu hình mới chạy test, và chỉ chạy **một lần**.

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|

Đường dẫn trace, nhãn thủ công và cách chọn mẫu:
- Cách chọn mẫu coherence (chốt trước khi xem điểm): vị trí là **dòng đầu tiên của các trang PDF 2–11** (trang 1 bắt đầu bằng quốc hiệu). Với mỗi vị trí, chấm chunk của từng cấu hình chứa vị trí đó.

## Phân tích và kết luận
- So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:
- Chiến lược chọn, đánh đổi, điều kiện áp dụng:
- Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:
- Nếu làm lại hoặc mở rộng, cải tiến gì?
