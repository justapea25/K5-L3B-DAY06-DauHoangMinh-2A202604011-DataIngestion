# Benchmark — Bộ luật Lao động 2019

File câu hỏi: [questions.jsonl](questions.jsonl), gồm 20 câu: 15 câu dev và 5 câu test.
Kiểm tra tự động bằng lệnh `python -m src.check_benchmark` (chạy trong `starter/`). Script kiểm tra số lượng câu, cách chia dev/test, giá trị filter, và xác nhận mỗi `evidence_quote` có trong văn bản trang `gold_page` (đã chuẩn hóa, bỏ qua khác biệt khoảng trắng).

## Trường dữ liệu
`id`, `split`, `type`, `question`, `expected_answer`, `gold_source_id`, `gold_page` (trang PDF, đánh số từ 1), `gold_article` (số Điều, để phân tích lỗi), `evidence_quote`, `filter`.
Các câu có filter có thêm `filter_source` (filter lấy từ cụm nào trong câu hỏi) và `confuser` (Điều dễ gây nhầm khi không lọc).

## Phân loại câu hỏi
| Loại | Số câu |
|---|---|
| Trực tiếp (`truc_tiep`) | 5 |
| Có điều kiện (`dieu_kien`) | 6 |
| Diễn đạt lại (`dien_dat_lai`) | 4 |
| Ngoại lệ (`ngoai_le`) | 1 |
| Có metadata filter (`metadata_filter`) | 4: q12, q13, q14 (dev), q20 (test) |

## Filter
- Trường dùng để lọc: `chapter` (số La Mã của Chương), lấy trực tiếp từ dòng "Chương X" trong văn bản.
- Giá trị filter là **input giả định được cung cấp trước khi truy xuất**: nó tương ứng với phạm vi mà người hỏi đã nêu trong câu (ví dụ "trong phần kỷ luật lao động" → Chương VIII). Filter không lấy từ gold source.
- Mỗi câu có filter đều có một Điều dễ gây nhầm (`confuser`) nằm ở chương khác, có nội dung gần giống. Ví dụ: thời hiệu kỷ luật (Điều 123) và thời hiệu tranh chấp (Điều 190); giờ làm của người chưa thành niên (Điều 146) và giờ làm thông thường (Điều 105).
- Với cấu hình C, câu không có filter được chạy **không lọc**, tức là giống hệt cấu hình B.

## Cách chia dev/test (chốt trước khi chạy thử)
- Chia theo **Điều**: 5 câu test dùng các Điều 46, 115, 128, 139, 190. Không câu dev nào dùng các Điều này.
- **Nguy cơ rò rỉ** (cùng chủ đề hoặc cùng chương giữa dev và test):
  - q14 (dev, Điều 123) và q20 (test, Điều 190) đều hỏi về "thời hiệu".
  - q12 (dev, Điều 137) và q18 (test, Điều 139) cùng thuộc Chương X.
  - q09, q10, q11 (dev, Điều 112–114) và q19 (test, Điều 115) cùng thuộc Mục "Thời giờ nghỉ ngơi".
- Tập test chỉ có 5 câu, nên mỗi câu chiếm 20% điểm Hit. Kết quả test chỉ mang tính minh họa.

## Tiêu chí chọn cấu hình (định nghĩa trước khi xem test)
Cấu hình được chọn **chỉ dựa trên dev**, theo thứ tự ưu tiên:
1. Evidence Hit@3 trên dev.
2. Nếu Hit@3 bằng nhau: Hit@1 trên dev.
3. Nếu vẫn bằng nhau: điểm coherence trung bình.
4. Nếu vẫn bằng nhau: tài nguyên (số chunk, thời gian ingest).

Sau khi đã cố định cấu hình, mới chạy test **một lần**. Không sửa chiến lược dựa trên kết quả test.

### Quyết định sau dev (ghi trước khi chạy test)
- Kết quả dev: A có Hit@1 9/15, Hit@3 14/15. B và C đều có Hit@1 14/15, Hit@3 15/15. Hai cấu hình B và C trả về kết quả **giống hệt nhau** cho cả 15 câu, vì 3 câu dev có filter (q12, q13, q14) khi không lọc vẫn cho top-3 đúng chương.
- B và C hòa ở cả 4 tiêu chí. Coherence và tài nguyên cũng như nhau vì hai cấu hình dùng chung chunk. **Quy tắc phá hòa bổ sung:** chọn cấu hình có filter, vì nó không làm giảm chỉ số dev nào và giới hạn được phạm vi khi người dùng cung cấp trước.
- **Cấu hình chọn: C.** Chưa có bằng chứng nào trên dev cho thấy filter cải thiện kết quả. Test được chạy một lần cho cả A, B và C để báo cáo.

## Nguồn gốc và kiểm chứng
- Câu hỏi được soạn từ văn bản đã chuẩn hóa. Đoạn trích bằng chứng được kiểm tra tự động bằng script.
- **Tác giả cần tự đọc lại** từng câu, đáp án và đoạn trích so với PDF gốc trước khi chạy thử. Có thể sửa hoặc thay câu. Sau khi chốt, ghi lại ngày chốt ở đây.
- Ngày chốt benchmark: 2026-11-14, trước lần chạy dev đầu tiên.
