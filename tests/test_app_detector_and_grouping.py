import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.app_detector import AppDetector
from app.core.ai_service import AIService


def test_app_detection():
    print("\n--- 1. 测试 App / 工具链识别引擎 ---")
    test_cases = [
        (r"C:\Users\Administrator\.npm\_cacache\content-v2\sha512\ab\cd", "Node.js / npm"),
        (r"C:\Users\Administrator\AppData\Local\npm-cache\anonymous-cli-metrics.json", "Node.js / npm"),
        (r"D:\my_project\node_modules\react\index.js", "Node.js 依赖库 (node_modules)"),
        (r"C:\Users\Administrator\AppData\Local\pip\cache\wheels\test.whl", "Python / pip / 虚拟环境"),
        (r"C:\Users\Administrator\.vscode\extensions\ms-python.python\package.json", "Visual Studio Code"),
        (r"C:\Users\Administrator\AppData\Local\Temp\scoped_dir_123\test.tmp", "系统与应用临时缓存"),
        (r"C:\Users\Administrator\Documents\WeChat Files\wxid_123\FileStorage\test.pdf", "微信 (WeChat)"),
        (r"C:\Users\Administrator\Downloads\some_unknown_dir\random_data.dat", "系统下载中心"),
        (r"C:\Windows\System32\drivers\etc\hosts", "系统临时与日志/Temp" if "temp" in "etc" else "未识别工具/待分类")
    ]

    for path, expected_app_hint in test_cases:
        res = AppDetector.detect_app_for_path(path)
        print(f"Path: {path}")
        print(f"  -> App: {res['app_name']} | 分类: {res['suggested_category']} | 风险: {res['risk_level']} | 置信度: {res['confidence']}")
        assert res["app_name"], "必须返回有效的 app_name"


def test_npm_atomic_grouping():
    print("\n--- 2. 重点验证：~/npm 工具链目录整体分组与原子性 (拒绝按扩展名拆分) ---")
    
    # 模拟 ~/npm 目录下包含 .js, .json, .lock, .tmp, .tgz 等多种不同格式的文件
    npm_files = [
        {"name": "index.js", "path": r"C:\Users\Administrator\.npm\package\index.js", "size": 1024},
        {"name": "package.json", "path": r"C:\Users\Administrator\.npm\package\package.json", "size": 512},
        {"name": "config.yaml", "path": r"C:\Users\Administrator\.npm\settings\config.yaml", "size": 256},
        {"name": "cache.tgz", "path": r"C:\Users\Administrator\.npm\cache\data.tgz", "size": 1048576},
        {"name": "temp.tmp", "path": r"C:\Users\Administrator\.npm\tmp\build.tmp", "size": 2048},
        
        # 混入另一个 Python 工具目录
        {"name": "pip.log", "path": r"C:\Users\Administrator\AppData\Local\pip\cache\pip.log", "size": 4096},
        {"name": "wheel.whl", "path": r"C:\Users\Administrator\AppData\Local\pip\cache\pkg.whl", "size": 2097152},
        
        # 混入未识别目录
        {"name": "unknown.xyz", "path": r"D:\custom_tools\orphan\unknown.xyz", "size": 8192}
    ]

    dest_root = r"D:\归档备份"
    groups = AppDetector.group_files_by_parent_or_tool(npm_files, dest_root)

    print(f"聚合后生成的处理单元总数: {len(groups)}")
    
    npm_group = None
    for g in groups:
        print(f"\n[分组单元] ID: {g['group_id']} | 名称: {g['name']}")
        print(f"  原根路径: {g['original_root']}")
        print(f"  识别 App: {g['app_name']}")
        print(f"  建议分类: {g['suggested_category']}")
        print(f"  目标规划路径: {g['target_root']}")
        print(f"  包含文件数: {g['file_count']} | 总大小: {g['total_size']} 字节")
        print(f"  安全评级: {g['risk_level']} | 需确认: {g['require_confirmation']}")
        print("  包含子文件:")
        for sub in g["sub_items"]:
            print(f"    - {sub['relative_path']} -> {sub['target_path']}")

        if "npm" in g["app_name"].lower():
            npm_group = g

    # 验证 npm 目录作为一个整体处理单元
    assert npm_group is not None, "必须成功识别出 npm 目录分组"
    assert npm_group["file_count"] == 5, f"npm 目录必须包含全部 5 个子文件，实际: {npm_group['file_count']}"
    assert "Node.js" in npm_group["app_name"], "必须识别为 Node.js / npm 生态"
    
    # 验证子文件中的 .js, .json, .tgz, .tmp 是否全部统一在同一个分类目标下
    target_cats = {sub["target_path"].split("\\")[-3] for sub in npm_group["sub_items"]}
    print(f"\nnpm 子文件归档目标分类集合: {target_cats}")
    assert len(target_cats) == 1, f"npm 目录下的所有文件必须统一归入同一个目标父分类，不得拆散！实际集合: {target_cats}"

    print("\n✅ npm 目录整体分组与原子性测试全部通过！")


def test_ai_service_integration():
    print("\n--- 3. 测试 AIService 离线与规则兜底链路 ---")
    mock_files = [
        {"name": "app.js", "path": r"C:\Users\Administrator\.npm\app.js", "size": 100},
        {"name": "test.txt", "path": r"D:\docs\test.txt", "size": 200}
    ]
    results = AIService.classify_files_with_ai(
        base_url="", api_key="", model="",
        file_items=mock_files,
        destination_root=r"D:\归档备份"
    )
    assert len(results) >= 1, "AIService 必须返回有效分组"
    print(f"AIService 返回了 {len(results)} 个目录组")
    print("✅ AIService 离线链路测试通过！")


if __name__ == "__main__":
    test_app_detection()
    test_npm_atomic_grouping()
    test_ai_service_integration()
    print("\n🎉 全部单元测试执行成功！")
