"""
离线基准评测数据集生成脚本 (320 组真实脱敏样例)
涵盖：
1. 开发工程与工具链 (Node.js, Python, Rust, Go, Java, CMake, Docker) - 60组
2. 办公与财务文档 (发票, 合同, 报销, 税务, 财务报表, 简历, 汇报PPT, 方案) - 70组
3. 媒体与设计素材 (4K视频, 录音, RAW照片, 设计PSD, 矢量图SVG) - 50组
4. 应用缓存与日志 (微信/QQ缓存, 浏览器缓存, 崩溃日志, 下载碎片) - 40组
5. 安装包与归档镜像 (Setup.exe, MSI, ISO, ZIP, 7Z, TAR.GZ) - 40组
6. 孤儿与未知低置信度文件 (未识别后缀, 杂散二进制, 随机哈希命名) - 30组
7. 系统关键路径与敏感安全凭证 (System32, ProgramData, .env, id_rsa, pem) - 30组
总计: 320 组
"""

import json
from pathlib import Path
from typing import List, Dict, Any


def generate_benchmark_dataset() -> List[Dict[str, Any]]:
    dataset: List[Dict[str, Any]] = []
    case_num = 1

    def add_case(
        name: str,
        is_directory: bool,
        files: List[Dict[str, Any]],
        expected_category: str,
        expected_app: str,
        expected_risk: str,
        should_require_conf: bool,
        is_system_path: bool = False,
        is_sensitive: bool = False,
        keywords: List[str] = None
    ):
        nonlocal case_num
        case_id = f"bench_{case_num:04d}"
        case_num += 1
        dataset.append({
            "id": case_id,
            "name": name,
            "is_directory": is_directory,
            "simulated_files": files,
            "expected_category": expected_category,
            "expected_app": expected_app,
            "expected_risk": expected_risk,
            "should_require_confirmation": should_require_conf,
            "is_system_path": is_system_path,
            "is_sensitive": is_sensitive,
            "keywords": keywords or []
        })

    base_time = 1740000000 # 2025-02-19

    # ============================================================
    # 1. 开发工程与工具链 (60组)
    # ============================================================
    # 1.1 Node.js / 前端 (20组)
    frontend_frameworks = [
        ("vue-admin-portal", ["package.json", "vite.config.ts", "src/main.ts", "src/App.vue", "tsconfig.json"]),
        ("react-dashboard-v3", ["package.json", "tsconfig.json", "src/index.tsx", "src/App.tsx", "public/index.html"]),
        ("nextjs-enterprise-web", ["package.json", "next.config.js", "pages/index.tsx", "styles/globals.css"]),
        ("nuxt3-ecommerce-store", ["package.json", "nuxt.config.ts", "app.vue", "components/Cart.vue"]),
        ("angular-crm-client", ["package.json", "angular.json", "src/app/app.module.ts"]),
        ("svelte-portfolio", ["package.json", "svelte.config.js", "src/routes/+page.svelte"]),
        ("electron-desktop-app", ["package.json", "electron-builder.yml", "src/main/index.ts", "src/renderer/index.html"]),
        ("express-api-service", ["package.json", "src/server.js", "src/routes/api.js"]),
        ("nest-microservice", ["package.json", "nest-cli.json", "src/main.ts", "src/app.module.ts"]),
        ("monorepo-lerna-turborepo", ["package.json", "turbo.json", "apps/web/package.json", "packages/ui/package.json"]),
        ("taro-miniapp-shop", ["package.json", "config/index.js", "src/app.config.ts"]),
        ("uni-app-mobile", ["package.json", "pages.json", "manifest.json", "main.js"]),
        ("webpack-legacy-bundle", ["package.json", "webpack.config.js", "src/index.js"]),
        ("rollup-lib-starter", ["package.json", "rollup.config.mjs", "src/index.ts"]),
        ("storybook-design-system", ["package.json", ".storybook/main.ts", "stories/Button.stories.tsx"]),
        ("react-native-ios-android", ["package.json", "App.tsx", "android/build.gradle", "ios/Podfile"]),
        ("remix-run-blog", ["package.json", "remix.config.js", "app/root.tsx"]),
        ("astro-docs-site", ["package.json", "astro.config.mjs", "src/pages/index.astro"]),
        ("solidjs-benchmark", ["package.json", "vite.config.ts", "src/App.tsx"]),
        ("fastify-rest-gateway", ["package.json", "server.js", "plugins/jwt.js"]),
    ]
    for proj_name, files in frontend_frameworks:
        sim_files = [
            {"name": f, "path": f"D:/Projects/frontend/{proj_name}/{f}", "size": 1024 + idx * 512, "mtime": base_time + idx * 3600}
            for idx, f in enumerate(files)
        ]
        add_case(
            name=proj_name,
            is_directory=True,
            files=sim_files,
            expected_category="代码项目与依赖 (Dev & Code)",
            expected_app="Node.js",
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["node", "package.json", "frontend"]
        )

    # 1.2 Python 工程 (15组)
    py_projects = [
        ("fastapi-rag-service", ["pyproject.toml", "main.py", "requirements.txt", "app/api/router.py"]),
        ("django-auth-platform", ["manage.py", "requirements.txt", "portal/settings.py", "portal/urls.py"]),
        ("flask-lightweight-webhook", ["app.py", "requirements.txt", "config.py"]),
        ("pytorch-llm-finetuning", ["train.py", "model.py", "requirements.txt", "dataset.py"]),
        ("celery-distributed-worker", ["tasks.py", "celery_app.py", "requirements.txt"]),
        ("scrapy-data-spider", ["scrapy.cfg", "spiders/spider.py", "items.py", "pipelines.py"]),
        ("poetry-cli-tool", ["pyproject.toml", "poetry.lock", "cli_tool/main.py"]),
        ("pipenv-data-cleaner", ["Pipfile", "Pipfile.lock", "cleaner.py"]),
        ("conda-env-simulation", ["environment.yml", "simulation.py"]),
        ("huggingface-diffusers-pipeline", ["generate.py", "pipeline.py", "requirements.txt"]),
        ("pytest-automation-suite", ["pytest.ini", "tests/test_api.py", "conftest.py"]),
        ("airflow-dags-repo", ["dags/daily_sync.py", "dags/etl_process.py", "requirements.txt"]),
        ("streamlit-dashboard", ["app.py", ".streamlit/config.toml", "requirements.txt"]),
        ("opencv-vision-inspector", ["detect.py", "utils.py", "requirements.txt"]),
        ("alembic-db-migration", ["alembic.ini", "alembic/env.py", "models.py"]),
    ]
    for proj_name, files in py_projects:
        sim_files = [
            {"name": f, "path": f"D:/Projects/python/{proj_name}/{f}", "size": 2048 + idx * 1024, "mtime": base_time + idx * 7200}
            for idx, f in enumerate(files)
        ]
        add_case(
            name=proj_name,
            is_directory=True,
            files=sim_files,
            expected_category="代码项目与依赖 (Dev & Code)",
            expected_app="Python",
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["python", "pyproject", "django", "fastapi"]
        )

    # 1.3 Rust / Go / Java / C++ / Docker (25组)
    systems_projects = [
        # Rust
        ("rust-highperf-engine", ["Cargo.toml", "Cargo.lock", "src/main.rs", "src/lib.rs"], "Cargo / Rust"),
        ("rust-crypto-wasm", ["Cargo.toml", "src/lib.rs"], "Cargo / Rust"),
        ("rust-tokio-proxy", ["Cargo.toml", "src/main.rs", "src/handler.rs"], "Cargo / Rust"),
        ("rust-cli-parser", ["Cargo.toml", "src/main.rs"], "Cargo / Rust"),
        ("rust-embedded-firmware", ["Cargo.toml", ".cargo/config.toml", "src/main.rs"], "Cargo / Rust"),
        # Go
        ("go-micro-order", ["go.mod", "go.sum", "main.go", "handlers/order.go"], "Go / Golang"),
        ("go-gin-api-gateway", ["go.mod", "main.go", "routers/api.go"], "Go / Golang"),
        ("go-grpc-storage", ["go.mod", "main.go", "proto/storage.proto"], "Go / Golang"),
        ("go-k8s-operator", ["go.mod", "main.go", "controllers/pod_watcher.go"], "Go / Golang"),
        ("go-cli-syncer", ["go.mod", "main.go", "cmd/root.go"], "Go / Golang"),
        # Java / Maven / Gradle
        ("spring-boot-finance-core", ["pom.xml", "src/main/java/Application.java", "src/main/resources/application.yml"], "Maven / Java"),
        ("spring-cloud-eureka", ["pom.xml", "src/main/java/EurekaServer.java"], "Maven / Java"),
        ("gradle-android-app", ["build.gradle", "settings.gradle", "app/build.gradle"], "Gradle / Java"),
        ("kotlin-ktor-service", ["build.gradle.kts", "src/main/kotlin/Application.kt"], "Gradle / Java"),
        ("quarkus-native-api", ["pom.xml", "src/main/java/GreetingResource.java"], "Maven / Java"),
        # C / C++ / CMake
        ("cmake-opengl-renderer", ["CMakeLists.txt", "src/main.cpp", "include/shader.h"], "CMake / C++"),
        ("cuda-matrix-mult", ["CMakeLists.txt", "src/kernel.cu", "src/main.cpp"], "CMake / C++"),
        ("embedded-stm32-hal", ["Makefile", "Core/Src/main.c", "Core/Inc/main.h"], "Makefile / C"),
        ("qt6-desktop-player", ["CMakeLists.txt", "main.cpp", "mainwindow.ui", "mainwindow.h"], "CMake / C++"),
        ("audio-dsp-vst-plugin", ["CMakeLists.txt", "PluginProcessor.cpp", "PluginProcessor.h"], "CMake / C++"),
        # Docker / DevOps
        ("k8s-helm-charts-infra", ["Chart.yaml", "values.yaml", "templates/deployment.yaml"], "DevOps / K8s"),
        ("docker-compose-stack", ["docker-compose.yml", "nginx.conf", "Dockerfile"], "Docker"),
        ("terraform-aws-cluster", ["main.tf", "variables.tf", "outputs.tf"], "Terraform"),
        ("ansible-server-playbooks", ["playbook.yml", "hosts.ini", "roles/common/tasks/main.yml"], "Ansible"),
        ("github-workflows-repo", [".github/workflows/ci.yml", ".github/workflows/deploy.yml"], "GitHub CI"),
    ]
    for proj_name, files, app_tag in systems_projects:
        sim_files = [
            {"name": f, "path": f"D:/Projects/systems/{proj_name}/{f}", "size": 4096 + idx * 1024, "mtime": base_time + idx * 3600}
            for idx, f in enumerate(files)
        ]
        add_case(
            name=proj_name,
            is_directory=True,
            files=sim_files,
            expected_category="代码项目与依赖 (Dev & Code)",
            expected_app=app_tag,
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["dev", app_tag.lower()]
        )

    # ============================================================
    # 2. 办公与财务文档 (70组)
    # ============================================================
    # 2.1 发票与财务凭证 (25组)
    invoices = [
        "2025年01月增值税电子普通发票_98231.pdf",
        "2025年02月增值税专用发票_北京数码科技_883201.pdf",
        "2025年03月阿里云服务器租赁发票_INV20250301.pdf",
        "2024年12月员工差旅报销单及发票凭据汇总.xlsx",
        "2025年Q1办公室房租物业开具发票_89234.pdf",
        "增值税专用发票_中国电信宽带费_202504.pdf",
        "办公设备采购发票_联想笔记本_20250218.pdf",
        "餐饮发票_客户接待宴请_20250115.pdf",
        "打车行程单及电子发票_滴滴出行_202503.pdf",
        "高铁电子客票发票报销凭证_上海到北京_20250320.pdf",
        "机票行程单及增值税发票_国航商务出行_202502.pdf",
        "Invoice_AWS_Cloud_Services_202501.pdf",
        "Invoice_GitHub_Enterprise_Subscription_2025.pdf",
        "Invoice_JetBrains_All_Products_Pack_2024.pdf",
        "Invoice_OpenAI_API_Platform_Credits_202502.pdf",
        "财务凭证汇总表_2024年度记账凭证_第12期.xlsx",
        "出纳日记账与银行流水对账单_2025年1月.xlsx",
        "企业所得税汇算清缴申报表_2024年度.pdf",
        "增值税纳税申报表及附列资料_202502.pdf",
        "年度财务审计报告_正规会计师事务所盖章版_2024.pdf",
        "应收账款催收函及对账单_2025Q1.docx",
        "供应商应付账款明细表_20250228.xlsx",
        "员工差旅费用报销申请表_市场部_张伟.xlsx",
        "项目研发费用加计扣除专项审计底稿_2024.xlsx",
        "固定资产盘点表与折旧明细账_2025.xlsx"
    ]
    for inv in invoices:
        add_case(
            name=inv,
            is_directory=False,
            files=[{"name": inv, "path": f"D:/Downloads/finance/{inv}", "size": 150000, "mtime": base_time}],
            expected_category="文档与多媒体资产 (Docs & Media)",
            expected_app="财务文档",
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["财务", "发票", "报销", "invoice"]
        )

    # 2.2 合同、协议与商务 (20组)
    contracts = [
        "软件定制开发委托合同_甲方终版_20250110.docx",
        "技术服务与系统运维保障协议书_2025.pdf",
        "企业保密协议(NDA)_双向签署盖章扫描件_2025.pdf",
        "全职劳动合同书_研发总监岗位_李明.pdf",
        "劳动合同补充协议_竞业限制与保密条款.docx",
        "商务战略合作框架协议_腾讯云生态合作_2025.pdf",
        "IDC机房机柜托管服务合同_2025年度续签.docx",
        "办公场地租赁合同_高新科技园区_2024-2027.pdf",
        "销售代理合作协议_华东区域独家分销_2025.docx",
        "SaaS软件企业版采购订单与服务条款_2025.pdf",
        "知识产权转让及专利独家授权协议.docx",
        "项目保修期承诺书与质量保证协议.pdf",
        "商业咨询服务协议_德勤管理顾问_2025.docx",
        "借款合同及质押担保协议_银行信贷.pdf",
        "采购框架协议_电子元器件供应商名录_2025.docx",
        "Master_Service_Agreement_MSA_Global_Tech_2025.pdf",
        "Software_License_Agreement_Enterprise_EULA.docx",
        "Data_Processing_Agreement_GDPR_Compliance.pdf",
        "Independent_Contractor_Agreement_Remote_Dev.docx",
        "Non_Disclosure_Agreement_Mutual_Confidentiality.pdf"
    ]
    for c in contracts:
        add_case(
            name=c,
            is_directory=False,
            files=[{"name": c, "path": f"D:/Documents/contracts/{c}", "size": 320000, "mtime": base_time}],
            expected_category="文档与多媒体资产 (Docs & Media)",
            expected_app="商务合同",
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["商务", "合同", "协议", "contract"]
        )

    # 2.3 人事、汇报、方案与资料 (25组)
    office_docs = [
        "高级Java架构师候选人_王强_求职简历.pdf",
        "资深前端开发工程师_陈晨_五年经验简历.docx",
        "AI算法科学家_技术背景及学术论文简历.pdf",
        "应聘登记表与背景调查授权书_张峰.pdf",
        "公司全体员工花名册及通讯录_2025年版.xlsx",
        "2024年终总结及2025年度战略规划汇报.pptx",
        "技术中台架构演进与微服务拆分方案.pptx",
        "大模型私有化部署实施与性能优化方案.docx",
        "用户需求说明书(PRD)_电商多端融合平台_v3.2.docx",
        "系统详细概要设计与接口文档_Swagger导出.pdf",
        "数据库表结构设计与字典字典说明书.xlsx",
        "网络安全等级保护三级测评整改报告.pdf",
        "ISO27001信息安全管理体系认证审核资料.pdf",
        "每周项目迭代进度同步会议纪要_2025W08.docx",
        "敏捷研发冲刺Sprint评审与复盘总结.pptx",
        "新员工入职培训手册与IT系统使用指南_2025.pdf",
        "岗位职责说明书与KPI考核评价标准_研发部.xlsx",
        "智慧园区智能化物联网工程招投标文件_技术标.docx",
        "政务云平台灾备切换与演练方案_2025.docx",
        "客户满意度问卷调查统计分析报告_Q1.xlsx",
        "市场调研分析报告_新能源汽车车载软件发展趋势.pdf",
        "产品白皮书_工业物联网数字孪生底座.pdf",
        "运维值班与突发事件应急响应处置手册.docx",
        "核心系统权限审批登记台账_202502.xlsx",
        "年度优秀员工评选名单及事迹材料.docx"
    ]
    for d in office_docs:
        add_case(
            name=d,
            is_directory=False,
            files=[{"name": d, "path": f"D:/Documents/office/{d}", "size": 800000, "mtime": base_time}],
            expected_category="文档与多媒体资产 (Docs & Media)",
            expected_app="办公文档",
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["文档", "简历", "汇报", "方案"]
        )

    # ============================================================
    # 3. 媒体与设计素材 (50组)
    # ============================================================
    # 3.1 视频素材 (18组)
    video_files = [
        "企业形象宣传片_4K调色终版_ProRes422.mov",
        "产品发布会现场全程实录_1080P_H264.mp4",
        "无人机航拍空镜素材_园区全貌_Dlog_001.mp4",
        "无人机航拍空镜素材_城市天际线_Dlog_002.mp4",
        "客户现场访谈视频切片_01_高清录制.mp4",
        "软件操作教程录屏教学_第01讲_环境搭建.mp4",
        "软件操作教程录屏教学_第02讲_快速上手.mp4",
        "短视频营销剪辑片段_竖屏9比16_01.mp4",
        "短视频营销剪辑片段_竖屏9比16_02.mp4",
        "年会舞台背景大屏循环动画_1080P.mp4",
        "3D产品三维渲染爆炸图动画_Alpha通道.mov",
        "Interview_CEO_Keynote_Speech_2025.mkv",
        "Conference_Livestream_Recording_Part1.flv",
        "Webinar_Technical_DeepDive_Session.mp4",
        "Motion_Graphics_Logo_Reveal_Animation.mov",
        "Camera_Raw_Footage_Sony_FX3_A001_C001.mov",
        "Camera_Raw_Footage_Sony_FX3_A001_C002.mov",
        "Screen_Recording_Bug_Reproduction_Issue_402.mp4"
    ]
    for v in video_files:
        add_case(
            name=v,
            is_directory=False,
            files=[{"name": v, "path": f"D:/Media/videos/{v}", "size": 450000000, "mtime": base_time}],
            expected_category="文档与多媒体资产 (Docs & Media)",
            expected_app="视频素材",
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["视频", "media", "mp4"]
        )

    # 3.2 音频与录音 (12组)
    audio_files = [
        "高管战略闭门会议现场录音_无损WAV_20250210.wav",
        "科技播客专访音频_第45期_已降噪混音.mp3",
        "视频配音旁白解说音轨_国语男声_专业播音.wav",
        "企业宣传片商业授权背景音乐BGM_激励激昂.mp3",
        "宣传片背景配乐_舒缓科技感无版权限制.mp3",
        "用户访谈录音纪要_第3位受访者.m4a",
        "客服电话服务录音抽检样本_202502.mp3",
        "Podcast_Episode_12_AI_Agents_Audio.mp3",
        "Sound_Effect_Click_Transition_Pack.wav",
        "Voiceover_English_Narrator_Studio_Master.wav",
        "Ambient_Office_Background_Noise.wav",
        "Original_Theme_Music_Orchestral.flac"
    ]
    for a in audio_files:
        add_case(
            name=a,
            is_directory=False,
            files=[{"name": a, "path": f"D:/Media/audio/{a}", "size": 25000000, "mtime": base_time}],
            expected_category="文档与多媒体资产 (Docs & Media)",
            expected_app="音频素材",
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["音频", "录音", "music"]
        )

    # 3.3 图像与平面设计工程 (20组)
    images_and_design = [
        "产品官网首页高清Banner海报设计_分层原稿.psd",
        "App界面UI视觉设计规范组件库_Figma导出.psd",
        "品牌形象识别手册VI_矢量标准Logo源文件.ai",
        "展会易拉宝与展板喷绘设计图_CMYK印刷级.psd",
        "产品包装盒刀版展开设计图_矢量刀线.ai",
        "公司矢量Logo图标全套透明背景合集.svg",
        "移动端功能图标ICON矢量库_24px_全集.svg",
        "团队集体合影留念_单反RAW原始底片_DSC0981.cr2",
        "公司年会活动现场抓拍精修组图_01.jpg",
        "公司年会活动现场抓拍精修组图_02.jpg",
        "员工证件照白底蓝底标准一寸二寸合集.png",
        "软件界面全套截图说明高清原图_01.png",
        "软件界面全套截图说明高清原图_02.png",
        "插画素材_科技感未来城市俯瞰图.png",
        "营销长图文海报_微信朋友圈传播版.jpg",
        "3D建模渲染产品效果图_白色背景_4K.png",
        "Banner_Header_Spring_Campaign_2025.psd",
        "Vector_Infographic_Architecture_Diagram.svg",
        "Illustration_Cybersecurity_Shield_Concept.ai",
        "Product_Photography_Studio_Shot_DSC_4421.arw"
    ]
    for img in images_and_design:
        add_case(
            name=img,
            is_directory=False,
            files=[{"name": img, "path": f"D:/Design/assets/{img}", "size": 35000000, "mtime": base_time}],
            expected_category="文档与多媒体资产 (Docs & Media)",
            expected_app="设计素材",
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["设计", "图片", "psd", "svg"]
        )

    # ============================================================
    # 4. 应用缓存、日志与临时碎片 (40组)
    # ============================================================
    caches_and_logs = [
        ("WeChat_File_Cache_Temp", ["FileStorage/Cache/temp_a82.dat", "FileStorage/Temp/wxa_8912.tmp", "Msg/msg_backup.db"], "微信 (WeChat)"),
        ("QQ_Data_Cache_Storage", ["Image/Group/img_8921.dat", "Audio/voice_002.amr", "FileRecv/temp_cache.tmp"], "腾讯 QQ"),
        ("Chrome_Browser_Cache_Data", ["Default/Cache/data_0", "Default/Cache/data_1", "Default/Cache/index", "Default/Code Cache/js/01"], "Google Chrome"),
        ("Edge_Browser_Cache_Data", ["Default/Cache/Cache_Data/data_0", "Default/GPUCache/data_0"], "Microsoft Edge"),
        ("Firefox_Profile_Cache", ["cache2/entries/892101", "startupCache/scriptCache.bin"], "Mozilla Firefox"),
        ("Nginx_Web_Server_Logs", ["access.log", "error.log", "nginx.pid.old"], "Nginx"),
        ("Apache_Httpd_Logs", ["access_log", "error_log", "ssl_request_log"], "Apache"),
        ("MySQL_Database_Slow_Logs", ["mysql-slow.log", "mysql-error.log", "binlog.000045"], "MySQL"),
        ("Redis_Dump_Snapshot_AOF", ["dump.rdb", "appendonly.aof"], "Redis"),
        ("Elasticsearch_Index_Logs", ["elasticsearch_server.log", "gc.log.00"], "Elasticsearch"),
        ("VSCode_Workspace_Cache", ["workspaceStorage/8923a1/state.vscdb", "CachedExtensions/ext_01.zip"], "Visual Studio Code"),
        ("IntelliJ_Idea_System_Cache", ["caches/attrib.dat", "index/filename.ver", "log/idea.log"], "IntelliJ IDEA"),
        ("PyCharm_Index_Cache", ["caches/content.dat", "log/pycharm.log"], "PyCharm"),
        ("Windows_Temp_Dump_Files", ["temp_setup_3812.tmp", "hsperfdata_admin/3891", "etilqs_982103"], "系统临时文件"),
        ("Adobe_AfterEffects_DiskCache", ["Disk Cache - 8923.aecache", "Adobe Premiere Pro Audio Prefs"], "Adobe Creative Cloud"),
        ("Blender_Autosave_Dumps", ["autosave1.blend", "autosave2.blend"], "Blender"),
        ("Unity_Project_Library_Cache", ["Artifacts/8a/8a921", "ShaderCache/3f/3f821"], "Unity Engine"),
        ("Unreal_Engine_DerivedDataCache", ["DDC/89/8921.ddc", "Saved/Logs/UnrealEditor.log"], "Unreal Engine"),
        ("Gradle_Build_Daemon_Logs", ["daemon/8.5/daemon-8912.out.log", "caches/journal-1/file-access.bin"], "Gradle"),
        ("Maven_Local_Repo_Transients", ["m2_cache.tmp", "resolver-status.properties"], "Maven"),
        ("Docker_Container_Log_Dumps", ["container-id-json.log", "daemon-stdout.log"], "Docker"),
        ("Kubernetes_Kubelet_Logs", ["kubelet.log", "containerd.log"], "Kubernetes"),
        ("Node_NPM_Cache_Tarballs", ["_cacache/content-v2/sha512/8a/8a921", "_cacache/index-v2/3f/3f99"], "Node.js / npm"),
        ("Python_Pip_Cache_Wheels", ["wheels/a1/b2/c3/package-1.0-py3-none-any.whl", "http/3f/8a/cache.dat"], "Python / pip"),
        ("Git_Pack_Loose_Objects", ["objects/pack/pack-89231.pack", "objects/pack/pack-89231.idx"], "Git"),
        ("CrashDump_Minidump_Files", ["crash_20250210_01.dmp", "crash_20250215_02.dmp"], "Windows Error Reporting"),
        ("Java_Crash_Fatal_Logs", ["hs_err_pid9812.log", "replay_pid9812.log"], "Java JVM"),
        ("System_Performance_ETW_Traces", ["perf_trace_001.etl", "kernellog.etl"], "Windows Performance"),
        ("Thunder_Download_Fragments", ["video_pack.mp4.td", "video_pack.mp4.td.cfg"], "迅雷下载"),
        ("BaiduNetdisk_Cache_Parts", ["baidunetdisk_upload.cfg", "temp_block_8912.downloading"], "百度网盘"),
        ("Steam_Game_Download_Chunks", ["depot_8921_chunk_01.bin", "downloading/state.vdf"], "Steam"),
        ("Tencent_WeGame_Patcher_Cache", ["patch_temp_001.dat", "wegame_repair.log"], "WeGame"),
        ("EpicGames_Manifest_Cache", ["Manifest_8921.manifest", "PendingUploads.dat"], "Epic Games"),
        ("Postman_Runtime_IndexedDB", ["IndexedDB/postman.indexeddb.leveldb/000005.ldb", "postman.log"], "Postman"),
        ("DBeaver_Query_History_Cache", ["history.txt", "dbeaver-debug.log"], "DBeaver"),
        ("OBS_Studio_Crash_Logs", ["Crash_2025-02-10_14-30-22.txt", "obs_log_current.txt"], "OBS Studio"),
        ("Photoshop_Scratch_VirtualDisk", ["Photoshop Temp8921389", "Photoshop Temp9812301"], "Adobe Photoshop"),
        ("Premiere_Peak_Audio_Files", ["media_audio.pek", "media_audio.cfa"], "Adobe Premiere"),
        ("Font_Cache_System_Dumps", ["font_cache_v3.bin", "FNTCACHE.DAT"], "Windows Font Cache"),
        ("DirectX_Shader_Cache_Folder", ["D3DSCache/89a1283.bin", "GPU_Shader_001.bin"], "DirectX"),
    ]
    for unit_name, files, app_tag in caches_and_logs:
        sim_files = [
            {"name": Path(f).name, "path": f"C:/Users/Public/AppData/Local/{unit_name}/{f}", "size": 1200000 + idx * 500000, "mtime": base_time}
            for idx, f in enumerate(files)
        ]
        add_case(
            name=unit_name,
            is_directory=True,
            files=sim_files,
            expected_category="缓存与临时数据 (Caches & Temp)",
            expected_app=app_tag,
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["cache", "缓存", "temp", "日志", "log"]
        )

    # ============================================================
    # 5. 安装包、镜像与压缩归档 (40组)
    # ============================================================
    installers_and_archives = [
        ("VSCodeSetup-x64-1.87.2.exe", 95000000, "安装程序"),
        ("Git-2.44.0-64-bit.exe", 62000000, "安装程序"),
        ("node-v20.11.1-x64.msi", 31000000, "安装程序"),
        ("python-3.12.2-amd64.exe", 26000000, "安装程序"),
        ("Docker Desktop Installer.exe", 650000000, "安装程序"),
        ("DBeaver-ce-24.0.0-x86_64-setup.exe", 115000000, "安装程序"),
        ("Postman-win64-Setup-10.23.5.exe", 160000000, "安装程序"),
        ("WeChatSetup_v3.9.9.exe", 185000000, "安装程序"),
        ("Tencent_QQ_9.9.8_x64.exe", 195000000, "安装程序"),
        ("BaiduNetdisk_7.38.0.exe", 89000000, "安装程序"),
        ("DingTalk_v7.5.10.exe", 210000000, "安装程序"),
        ("Feishu-win32-x64-7.12.7.exe", 230000000, "安装程序"),
        ("Bandizip-7.32-x64-setup.exe", 12000000, "安装程序"),
        ("7z2301-x64.exe", 2100000, "安装程序"),
        ("Everything-1.4.1.1024.x64-Setup.exe", 3200000, "安装程序"),
        ("PotPlayerSetup64.exe", 35000000, "安装程序"),
        ("OBS-Studio-30.0.2-Full-Installer-x64.exe", 130000000, "安装程序"),
        ("SteamSetup.exe", 2800000, "安装程序"),
        ("EpicInstaller-15.17.1.msi", 58000000, "安装程序"),
        ("NVIDIA-GeForce-GameReady-551.61.exe", 680000000, "安装程序"),
        ("ubuntu-24.04-desktop-amd64.iso", 4900000000, "系统镜像"),
        ("CentOS-Stream-9-latest-x86_64-dvd1.iso", 9800000000, "系统镜像"),
        ("Windows11_Business_x64_23H2.iso", 5600000000, "系统镜像"),
        ("archlinux-2024.02.01-x86_64.iso", 1100000000, "系统镜像"),
        ("debian-12.5.0-amd64-netinst.iso", 650000000, "系统镜像"),
        ("company_source_code_backup_20241231.tar.gz", 2500000000, "归档压缩包"),
        ("mysql_production_database_dump_full.sql.gz", 1800000000, "归档压缩包"),
        ("frontend_dist_production_build_v2.0.zip", 45000000, "归档压缩包"),
        ("user_uploaded_avatars_archive_2024.tar", 850000000, "归档压缩包"),
        ("annual_financial_records_scanned_docs.7z", 1200000000, "归档压缩包"),
        ("design_assets_high_resolution_backup.zip", 3400000000, "归档压缩包"),
        ("server_access_logs_history_archive.tar.bz2", 670000000, "归档压缩包"),
        ("machine_learning_dataset_coco2017.zip", 19000000000, "归档压缩包"),
        ("pretrain_model_weights_checkpoint_fp16.bin.gz", 8500000000, "归档压缩包"),
        ("android_sdk_commandlinetools_win-11076708.zip", 145000000, "归档压缩包"),
        ("cmake-3.28.3-windows-x86_64.zip", 48000000, "归档压缩包"),
        ("ninja-win-v1.11.1.zip", 850000, "归档压缩包"),
        ("redis-windows-7.0.4.zip", 12000000, "归档压缩包"),
        ("nginx-1.24.0-stable.zip", 3800000, "归档压缩包"),
        ("ffmpeg-master-latest-win64-gpl.zip", 92000000, "归档压缩包"),
    ]
    for pkg_name, size_b, app_label in installers_and_archives:
        add_case(
            name=pkg_name,
            is_directory=False,
            files=[{"name": pkg_name, "path": f"D:/Downloads/installers/{pkg_name}", "size": size_b, "mtime": base_time}],
            expected_category="安装包与压缩镜像 (Packages & Images)" if "安装" in app_label else "文档与多媒体资产 (Docs & Media)",
            expected_app=app_label,
            expected_risk="低风险",
            should_require_conf=False,
            keywords=["installer", "安装包", "iso", "zip", "exe"]
        )

    # ============================================================
    # 6. 孤儿与未知低置信度文件 (30组)
    # ============================================================
    # 这些文件必须归入“待人工确认”，且 require_confirmation 必须为 True！
    unknown_orphans = [
        ("orphan_blob_a9821.xyz", 1024),
        ("dump_memory_segment_440.raw", 8192000),
        ("temp_hash_00192384a8bc92.chk", 5120),
        ("unknown_format_payload.bin", 65536),
        ("transient_state_machine.dat", 4096),
        ("legacy_proprietary_v1.dbf_old", 131072),
        ("unrecognized_stream_codec.h26x", 524288),
        ("firmware_decompiled_slice.hex", 262144),
        ("packet_capture_unsupported.pcapng_corrupt", 1048576),
        ("intermediate_ast_graph.dot_tmp", 16384),
        ("cache_block_unindexed_89.001", 32768),
        ("cache_block_unindexed_89.002", 32768),
        ("raw_sensor_telemetry_dump.log_bin", 204800),
        ("unregistered_extension_test.qazwsx", 1024),
        ("cryptic_symbol_table.sym_dump", 8192),
        ("undocumented_hardware_regs.map_raw", 4096),
        ("corrupted_archive_header.rar_part", 999999),
        ("unfinished_bittorrent_piece.piece_34", 16777216),
        ("temp_swap_pagefile_fragment.swp", 33554432),
        ("random_bytes_entropy_pool.rnd", 65536),
        ("obfuscated_javascript_bytecode.jsc", 12288),
        ("decompiled_dalvik_bytecode.dex_stub", 24576),
        ("microcontroller_eeprom_dump.eep", 2048),
        ("unsupported_vector_gis_shape.shp_corrupt", 512000),
        ("custom_font_bitmap_metrics.fnt_raw", 18432),
        ("leftover_uninstaller_script.rem_dat", 3072),
        ("backup_snapshot_incompleted.bak_tmp", 4194304),
        ("unknown_diagnostic_trace.diag_raw", 81920),
        ("quantum_simulation_matrix.mtx_bin", 10485760),
        ("unnamed_binary_blob_00.bin_dat", 7777),
    ]
    for orphan, size_b in unknown_orphans:
        add_case(
            name=orphan,
            is_directory=False,
            files=[{"name": orphan, "path": f"D:/Downloads/misc/{orphan}", "size": size_b, "mtime": base_time}],
            expected_category="未分类/待人工确认",
            expected_app="未识别应用",
            expected_risk="中风险",
            should_require_conf=True, # 关键防线：未知必须人工确认
            keywords=["unknown", "未知", "orphan"]
        )

    # ============================================================
    # 7. 系统关键路径与敏感安全凭证 (30组)
    # ============================================================
    # 7.1 系统底层关键路径 (15组) - 必须高风险且 require_confirmation=True！
    system_paths = [
        ("C:/Windows/System32/drivers/etc/hosts", "hosts", 1024),
        ("C:/Windows/System32/kernel32.dll", "kernel32.dll", 1200000),
        ("C:/Windows/System32/cmd.exe", "cmd.exe", 320000),
        ("C:/Windows/System32/config/SAM", "SAM", 65536),
        ("C:/Windows/System32/config/SYSTEM", "SYSTEM", 12500000),
        ("C:/Windows/regedit.exe", "regedit.exe", 450000),
        ("C:/Windows/explorer.exe", "explorer.exe", 5200000),
        ("C:/Windows/Boot/EFI/bootmgfw.efi", "bootmgfw.efi", 1800000),
        ("C:/ProgramData/Microsoft/Windows/Start Menu/Programs/Startup/desktop.ini", "desktop.ini", 256),
        ("C:/Windows/SysWOW64/ntdll.dll", "ntdll.dll", 2100000),
        ("C:/Program Files/Common Files/system_service.dll", "system_service.dll", 850000),
        ("C:/Windows/win.ini", "win.ini", 512),
        ("C:/Windows/system.ini", "system.ini", 512),
        ("C:/Windows/System32/hal.dll", "hal.dll", 780000),
        ("C:/Windows/System32/user32.dll", "user32.dll", 1950000),
    ]
    for full_p, fname, sz in system_paths:
        add_case(
            name=fname,
            is_directory=False,
            files=[{"name": fname, "path": full_p, "size": sz, "mtime": base_time}],
            expected_category="系统关键/需人工确认",
            expected_app="Windows 系统核心",
            expected_risk="高风险",
            should_require_conf=True,
            is_system_path=True,
            is_sensitive=True,
            keywords=["system", "windows", "高风险"]
        )

    # 7.2 隐私凭据与密钥 (15组) - 严禁内容抽样！
    sensitive_credentials = [
        (".env", "D:/Projects/backend/.env", 850),
        (".env.production", "D:/Projects/backend/.env.production", 1200),
        (".env.local", "D:/Projects/web/.env.local", 640),
        ("id_rsa", "C:/Users/Admin/.ssh/id_rsa", 3240),
        ("id_ed25519", "C:/Users/Admin/.ssh/id_ed25519", 410),
        ("jwt_private_key.pem", "D:/Certificates/jwt_private_key.pem", 1820),
        ("server_ssl.key", "D:/Nginx/ssl/server_ssl.key", 1700),
        ("service_account_credentials.json", "D:/GCP/service_account_credentials.json", 2400),
        ("aws_credentials.ini", "C:/Users/Admin/.aws/credentials", 520),
        ("kube_config", "C:/Users/Admin/.kube/config", 4800),
        ("database_password_vault.kdbx", "D:/Secrets/database_password_vault.kdbx", 65536),
        ("pgpass.conf", "C:/Users/Admin/AppData/Roaming/postgresql/pgpass.conf", 310),
        ("npm_auth_token.npmrc", "C:/Users/Admin/.npmrc", 180),
        ("github_pat_token.txt", "D:/Notes/github_pat_token.txt", 120),
        ("alipay_private_key_pkcs8.pem", "D:/Payment/alipay_private_key_pkcs8.pem", 1680),
    ]
    for fname, full_p, sz in sensitive_credentials:
        add_case(
            name=fname,
            is_directory=False,
            files=[{"name": fname, "path": full_p, "size": sz, "mtime": base_time}],
            expected_category="代码项目与依赖 (Dev & Code)" if "env" in fname or "npm" in fname else "安全凭证与私钥",
            expected_app="敏感凭据/密钥",
            expected_risk="高风险",
            should_require_conf=True,
            is_system_path=False,
            is_sensitive=True,
            keywords=["sensitive", "secret", "token", "key"]
        )

    return dataset


if __name__ == "__main__":
    data = generate_benchmark_dataset()
    out_path = Path("tests/fixtures/organizer_benchmark_dataset.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] Generated benchmark dataset: {len(data)} cases to {out_path}")
