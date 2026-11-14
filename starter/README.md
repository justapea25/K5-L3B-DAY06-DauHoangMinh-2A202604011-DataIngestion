# Pipeline · Bộ luật Lao động 2019 → PostgreSQL + pgvector

Pipeline gồm các bước: nạp file PDF → chuẩn hóa văn bản → tách cấu trúc Chương/Mục/Điều → chia chunk theo 2 cách (A, B) → tạo embedding bằng `intfloat/multilingual-e5-small` → lưu vào pgvector → chạy benchmark cho 3 cấu hình (A, B, C).

## Môi trường đã dùng cho kết quả trong báo cáo
| Thành phần | Phiên bản / cấu hình |
|---|---|
| Hệ điều hành | macOS 14.5, Apple Silicon (arm64) |
| Python | 3.12.6 (venv `starter/.venv`) |
| Docker | Docker Desktop 4.99.0 (Engine 29.9.3, Compose v5.7.0) |
| Database | `pgvector/pgvector:0.8.7-pg16` (PostgreSQL 16.16, pgvector 0.8.7), cổng `127.0.0.1:55433` |
| Embedding | `intfloat/multilingual-e5-small`, revision `614241f6`, 384 chiều, chuẩn hóa L2, tiền tố `passage: ` / `query: `, chạy trên **CPU** |
| Thư viện | Xem [requirements.txt](requirements.txt) |
| Chi phí | 0 USD (không gọi API nào) |


## 1. Cài đặt
Các lệnh dưới đây chạy trong thư mục `starter/`:

```bash
cd starter
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cp .env.example .env               # chỉ chứa DATABASE_URL local, không cần API key
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py      # kỳ vọng: "Setup OK"
```

Lần chạy đầu tiên sẽ tự tải model e5-small (khoảng 470 MB) từ Hugging Face.

## 2. Chạy pipeline
```bash
python -m src.prepare          # đọc PDF, chuẩn hóa, chia chunk A/B, ghi manifest và log
python -m src.index            # tạo embedding và upsert vào pgvector (chạy lại lần 2 để kiểm tra không trùng)
python -m src.check_benchmark  # kiểm chứng evidence của 20 câu trên văn bản đã chuẩn hóa
python -m src.run              # chạy dev cho A/B/C (dùng để chọn cấu hình)
python -m src.run --split test # chạy test MỘT lần, sau khi đã chốt cấu hình
```

Thử truy vấn một câu bất kỳ:
```bash
python -m src.index --query "thời gian thử việc tối đa" --strategy A
python -m src.index --query "nghỉ bao nhiêu phút mỗi ngày" --chapter X   # cấu hình C (B + filter)
```

Dừng database nhưng vẫn giữ dữ liệu: `docker compose -p day6_student_starter stop`.

## 3. Ba cấu hình
| | Cách chia chunk | Filter | Bảng trong database |
|---|---|---|---|
| A | Cửa sổ cố định 500 ký tự, overlap 50, cắt trên toàn văn bản | Không | `strategy = 'A'` |
| B | Mỗi Điều một chunk, tối đa 1.500 ký tự; Điều dài hơn thì tách theo khoản/điểm và lặp lại tiêu đề Điều | Không | `strategy = 'B'` |
| C | Giống B (dùng chung các dòng dữ liệu) | `chapter = X` nếu câu hỏi có filter | `strategy = 'B'` + `WHERE chapter = %s` |

Tìm kiếm là **exact** (quét tuần tự, không dùng index ANN), metric cosine (`<=>`), top-k = 3.

## 4. Nạp lại và chống trùng
- Khóa chính của bảng là `(strategy, chunk_id)`. `chunk_id` cố định theo vị trí, ví dụ `bllđ-2019:B:art025:0` hoặc `bllđ-2019:A:0047`.
- Mỗi chunk có `content_hash`. Khi nạp lại, chunk có hash không đổi sẽ **không** được tạo embedding lại; chunk có hash thay đổi sẽ được upsert.
- Chunk không còn tồn tại sau khi chia lại sẽ bị **xóa** (`delete_obsolete`).
- Script dừng với lỗi nếu số dòng trong database khác số chunk trong file.
- Minh chứng: [results/index_log.json](results/index_log.json). Lần 1 tạo embedding cho 421 + 252 chunk; lần 2 bỏ qua cả 673 chunk, số dòng trùng = 0.

## 5. Cấu trúc file
```text
starter/
├── data/bo-luat-lao-dong-2019.pdf   # corpus (manifest: ../data/manifest.json)
├── src/
│   ├── ingestion.py        # đọc PDF theo trang, chuẩn hóa NFC, ghép dòng bị ngắt, gắn Chương/Mục/Điều
│   ├── chunking.py         # fixed_size (A), by_article (B), thống kê chunk
│   ├── prepare.py          # chạy bước dữ liệu, ghi manifest, pages, chunks, ingest_log
│   ├── embeddings.py       # E5Embedder: model local, báo lỗi rõ ràng, không dùng vector giả
│   ├── store.py            # PgVectorStore: schema, upsert, delete_obsolete, search có filter (tham số hóa SQL)
│   ├── index.py            # tạo embedding và nạp dữ liệu (idempotent), truy vấn thử
│   ├── check_benchmark.py  # kiểm tra benchmark: số câu, cách chia, filter, evidence trên đúng trang
│   ├── evaluation.py       # Hit@1, Evidence Hit@3, phát hiện evidence bị tách, tuân thủ filter
│   └── run.py              # chạy A/B/C cho dev/test, ghi trace, metrics, bảng chấm tay
└── results/
    ├── pages.jsonl                 # văn bản đã chuẩn hóa theo từng trang PDF
    ├── chunks_A.jsonl, chunks_B.jsonl
    ├── ingest_log.json             # lỗi trang, kiểm tra cấu trúc, thời gian, thống kê chunk
    ├── index_log.json              # các lần nạp, số chunk tạo embedding/bỏ qua/xóa, số dòng trùng
    ├── traces_dev.jsonl, traces_test.jsonl   # top-3 cho mỗi câu × cấu hình: text, score, metadata, hit
    ├── metrics_dev.json, metrics_test.json   # Hit@1/Hit@3 (n/N), tuân thủ filter, model đã dùng
    └── audit_coherence.csv, audit_metadata_test.csv, audit_grounding_test.csv   # nhãn chấm tay
```

Benchmark nằm ở [../benchmark/](../benchmark/); nhật ký thí nghiệm ở [../artifacts/experiment_log.csv](../artifacts/experiment_log.csv).

## Khả năng tái lập
- `prepare` cho kết quả xác định: chạy lại ra file giống hệt (đã kiểm tra bằng sha1).
- Embedding chạy trên CPU với cùng revision model, nên score có thể lệch rất nhỏ (khoảng 1e-6) giữa các máy.
- Không có bước nào dùng số ngẫu nhiên, nên không cần seed.
