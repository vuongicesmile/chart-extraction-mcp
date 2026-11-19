# Kiểm thử Chart Extraction MCP

## Phương pháp

Bộ 12 câu hỏi trong `scripts/benchmark.py` dùng PDF giả lập có ba giá trị Q1/Q2/Q3 là 25/50/75. So sánh hai chat độc lập trên cùng model. Lượt RAG dùng tệp đính kèm ở chế độ toàn văn. Lượt MCP bật kết nối Chart Extraction và yêu cầu model gọi `extract_chart` với đúng UUID tệp. Chương trình ghi đáp án, tool thực sự được gọi, nguồn và độ trễ dưới dạng JSONL.

Chạy trên Open WebUI thử nghiệm đã kết nối MCP. `OPENWEBUI_TEST_TOKEN` là token đăng nhập của tài khoản thử có quyền dùng kết nối. Chỉ dùng dữ liệu giả lập với provider bên ngoài.

```bash
PYTHONPATH=tests uv run python -c 'from conftest import bar_pdf; from pathlib import Path; Path("/tmp/quarterly-revenue-test.pdf").write_bytes(bar_pdf(raster=True))'
uv run python scripts/benchmark.py /tmp/quarterly-revenue-test.pdf \
  --url http://127.0.0.1:3002 > results.jsonl
```

Độ trễ tính từ lúc gửi yêu cầu chat tới lúc có câu trả lời đã hoàn tất trong Open WebUI. Báo cáo chấm theo đáp án ngắn mong đợi và ghi riêng việc model thực sự gọi tool. Bộ thử giả lập nhỏ để tái hiện, nên kết quả chưa đại diện cho mọi bố cục PDF hoặc model.

## Kết quả trên Open WebUI v0.13.4 và GLM-4-Flash

| Chỉ số | RAG-only | RAG + MCP |
| --- | ---: | ---: |
| Đáp đúng | 1/12 | 11/12 |
| Lượt gọi thành công `extract_chart` | 0/12 | 12/12 |
| Có nguồn trong câu trả lời hoặc metadata | 12/12 | 12/12 |
| Độ trễ trung vị | 2,0 giây | 11,1 giây |

PDF benchmark nhúng ảnh biểu đồ nên phần text layer chỉ có caption. Lượt MCP còn sai ở câu hỏi tính khoảng chênh lệch. Model nêu đúng hai giá trị 75 và 25 nhưng không thực hiện phép trừ. Số liệu đọc từ tool vẫn đầy đủ.

Đã kiểm tra thêm bằng Open WebUI thử nghiệm, sử dụng hai tài khoản riêng. Chủ tệp đọc được Q2 = 50, lần gọi lại báo cache hit, tài khoản còn lại bị từ chối trên đúng UUID đó. Docker OCR đọc được tiêu đề, hai trục, đơn vị USD và 25/50/75 từ biểu đồ ảnh mẫu. Vision tùy chọn đã đọc được cùng bộ số trên ảnh crop giả lập bằng `glm-4v-flash`.

Ứng dụng chính đã lưu kết nối **Chart Extraction** với auth **Session** và quyền mặc định cho admin. So sánh 12 câu thực hiện trong môi trường riêng với dữ liệu giả lập.

## Đối chứng biểu đồ tròn trong PDF

Hai PDF giả lập có cùng text layer và khác lát màu chiếm 60%. Đây là cặp mẫu của [báo cáo Open WebUI](https://github.com/open-webui/open-webui/discussions/11496#discussioncomment-19727262). Trên Open WebUI v0.13.4, `glm-4v-flash` đoán sai hoặc trả lời không xác định khi chỉ nhận PDF, nhưng đọc đúng cả hai trang dưới dạng ảnh. Với MCP mới, `glm-4-flash` gọi `extract_chart` qua Session và đọc được cả hai PDF gốc, trong môi trường thử nghiệm bật MCP và tắt Vision fallback.

| Lát thực tế | PDF qua extractor mặc định | PDF qua MCP |
| --- | --- | --- |
| Xanh dương | Đỏ | Xanh dương, khoảng 60%, trang 1 |
| Xanh lá | Không xác định | Xanh lá, khoảng 60%, trang 1 |

`tests/test_pie_chart.py` tạo lại hai PDF bằng ReportLab và kiểm tra kết quả qua MCP HTTP, gồm phát hiện, trích xuất, nguồn và cache. Các ca bổ sung kiểm tra hình không khép kín, các lát bằng nhau và kết quả Vision khi ảnh raster có lát lớn nhất nhưng thiếu nhãn số. Bài Vision raster dùng provider giả lập. Hai lượt chat với PDF vector dùng Open WebUI và model Z.ai thật.
