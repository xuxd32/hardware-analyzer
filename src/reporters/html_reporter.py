"""
简化HTML报告生成器
"""

from pathlib import Path
from datetime import datetime


class HTMLReporter:
    """HTML报告生成器"""
    
    def __init__(self, output_dir):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_report(self, analysis_results, schematic_path):
        """生成HTML报告"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.output_dir / f"analysis_report_{timestamp}.html"
        
        html_content = self._build_html(analysis_results, schematic_path)
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return report_path
    
    def _build_html(self, results, schematic_path):
        """构建HTML内容"""
        issues = results.get('all_issues', [])
        total_issues = len(issues)
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>硬件分析报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; }}
        h1 {{ color: #333; border-bottom: 3px solid #667eea; padding-bottom: 10px; }}
        .summary {{ background: #f8f9fa; padding: 20px; margin: 20px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #667eea; color: white; }}
        .critical {{ color: #ff4757; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>硬件分析报告</h1>
        <div class="summary">
            <p><strong>原理图:</strong> {schematic_path}</p>
            <p><strong>时间:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
            <p><strong>问题:</strong> {total_issues}</p>
        </div>
        <table><tr><th>#</th><th>元件</th><th>问题</th><th>级别</th></tr>
"""
        
        for i, issue in enumerate(issues, 1):
            html += f"<tr><td>{i}</td><td>{issue.get('component', '-')}</td><td>{issue.get('issue', '-')}</td><td>{issue.get('severity', 'medium')}</td></tr>\n"
        
        html += "</table></div></body></html>"
        return html
