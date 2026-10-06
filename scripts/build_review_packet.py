"""Package the existing 30 answers for explicit human review; calls no models."""
from pathlib import Path
import hashlib
import html
import json
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.evaluation import validate_dataset, load_json, EvaluationReviews
from scripts.score_landing import review_template, validate_report, score


def main():
    dataset_path = ROOT / "examples/minimum_landing_eval_v2.json"
    report_path = ROOT / "test_output/minimum-landing/bilingual-v2-report.json"
    dataset, report = validate_dataset(load_json(dataset_path)), load_json(report_path)
    rows = validate_report(dataset, report)
    assert len(dataset["cases"]) == 30 and len(rows) == 30
    output = ROOT / "output/30题人工审核"
    output.mkdir(parents=True, exist_ok=True)
    template = review_template(dataset, report)
    EvaluationReviews.model_validate(template)
    score(dataset, report, template)
    sources = {}
    for document in dataset["documents"]:
        source = ROOT / document["path"]
        recorded = next(item for item in report["inputs"] if item["key"] == document["key"])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == recorded["sha256"]
        shutil.copyfile(source, output / source.name)
        sources[document["key"]] = {"filename": source.name, "document_id": recorded["document_id"]}
    shutil.copyfile(dataset_path, output / "dataset.json")
    shutil.copyfile(report_path, output / "machine-report.json")
    (output / "review-template.json").write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data = {"template": template, "sources": sources,
            "cases": [{**case, "machine": rows[case["id"]]} for case in dataset["cases"]]}
    shell = (ROOT / "scripts/review_packet.html").read_text(encoding="utf-8")
    encoded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    (output / "审核入口.html").write_text(shell.replace("__REVIEW_DATA__", encoded), encoding="utf-8")
    markdown = ["# 30题人工审核", "", "这是已保存的离线机器结果，使用 hash 向量与资料摘录，尚未接入实际语义和生成模型。参考标签也需要核对。请先判断原页是否支持参考，再判断答案和引用。", "", "便捷填写请打开同目录的 审核入口.html；填写审核人、三项判断和理由，导出 JSON。所有初始结论均为未审核。", ""]
    escape = html.escape
    for index, case in enumerate(data["cases"], 1):
        answer = case["machine"].get("answer", {})
        source = sources[case["document"]]["filename"]
        markdown += [f"## {index}. {case['query']}", "", f"编号：{case['id']}；原文：[{source}]({source})；参考页：{case['pages'] or '无指定页，请确认文档是否缺少答案'}", "",
            f"待核对参考：{'文档应可回答' if case['answerable'] else '文档应无法回答'}；参考片段：{'、'.join(case['expected_answer_fragments']) or '无'}", "",
            "机器答案（完整）：", "", "<pre>" + escape(answer.get("answer", case["machine"].get("error", "未执行"))) + "</pre>", "",
            "机器引用：", "", "<pre>" + escape(json.dumps(answer.get("citations", []), ensure_ascii=False, indent=2)) + "</pre>", "",
            "人工填写：参考标签 □确认 □错误 □不确定；答案 □正确 □错误 □不确定；引用 □支持 □不支持 □不适用 □不确定。", "", "审核人：______　时间：______　理由／修正：______", ""]
    (output / "30题完整审核表.md").write_text("\n".join(markdown), encoding="utf-8")
    (output / "README.md").write_text("""# 审核方式

先解压整个目录，再双击 审核入口.html。每题有完整机器答案、待核对参考和原 PDF 页码链接。打开原文核对，填写三项判断、理由和审核人，点击导出审核结果。JSON 文件交回后可导入评分，不需要再次调用模型。浏览器缓存只是便利功能，离开前请导出 JSON，已导出结果可导入继续填写。

这是 2026年10月4日保存的 30 题结果，15 英文、15 中文来自两份实际 PDF；翻译对共享证据，不能作为独立保留集。当前使用 hash 向量与 extractive 资料摘录，不是实际语义模型与生成模型的质量验收。27 题为待核对摘录、3 题拒答；人工审核初始为 0/30。参考标签同样可能有错，不要先默认参考正确。

每题核对三件事：参考标签与原页是否一致；答案是否回答了问题（拒答也需判断合理性）；引用页是否支持答案。无证据或有歧义时选择不确定并注明理由。不要以出现数字、关键词或引用页码就判定答案正确。

资料与机器报告的版本指纹保存在 review-template.json。导出结果必须匹配同一数据集及报告；参考标签修正后要保留原版、重新生成报告，再审核新结果。包内无预填通过结论，也不会上传你的审核内容。
""", encoding="utf-8")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in output.iterdir() if path.is_file() and path.name != "manifest.json"}
    (output / "manifest.json").write_text(json.dumps({"case_count": 30, "human_reviewed": 0, "real_model_validation": False, "files": hashes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = ROOT / "output/30题人工审核包.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as target:
        for path in sorted(output.iterdir()):
            if path.is_file():
                target.write(path, "30题人工审核/" + path.name)
    print(json.dumps({"cases": 30, "human_reviewed": 0, "output": str(output), "zip": str(archive)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
