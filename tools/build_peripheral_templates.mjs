import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const outputDir = new URL("../payroll_ui/static/templates/", import.meta.url);
await fs.mkdir(outputDir, { recursive: true });

const dark = "#1F4E78";
const light = "#D9EAF7";
const input = "#FFF2CC";

function title(sheet, range, text) {
  const cell = sheet.getRange(range);
  cell.values = [[text]];
  cell.format = { font: { bold: true, color: "#FFFFFF", size: 14 }, fill: dark, horizontalAlignment: "left", verticalAlignment: "center" };
}

function header(sheet, range) {
  const cells = sheet.getRange(range);
  cells.format = { font: { bold: true, color: "#FFFFFF" }, fill: dark, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true, borders: { preset: "all", style: "thin", color: "#FFFFFF" } };
}

function editable(sheet, range) {
  sheet.getRange(range).format = { fill: input, borders: { preset: "all", style: "thin", color: "#D9D9D9" }, verticalAlignment: "center" };
}

async function renewalTemplate() {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("8月");
  sheet.showGridLines = false;
  const widths = [8, 12, 14, ...Array(5).fill(9), 10, ...Array(15).fill(9), 10, 12, 12, 12, 10, 14];
  widths.forEach((width, index) => { sheet.getCell(0, index).format.columnWidth = width; });
  sheet.getRange("A1:AD2").values = [["序号", "学科组", "教师", "1V1课时", null, null, null, null, null, "班课", null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, "小班领航伴学课次", null, null, null, "总计"], [null, null, null, 1, 2, 3, 4, 5, "合计", 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, "合计", 1, 2, 3, "合计", null]];
  header(sheet, "A1:AD2");
  sheet.getRange("A3:AD5").values = [
    [1, "示例学科组", "教师甲", 0, 0, 0, 0, 0, null, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, null, 0, 0, 0, null, null],
    [2, "示例学科组", "教师乙", 0, 0, 0, 0, 0, null, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, null, 0, 0, 0, null, null],
    [3, "示例学科组", "教师丙", 0, 0, 0, 0, 0, null, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, null, 0, 0, 0, null, null],
  ];
  sheet.getRange("I3").formulas = [["=SUM(D3:H3)"]]; sheet.getRange("I3:I5").fillDown();
  sheet.getRange("Y3").formulas = [["=SUM(J3:X3)"]]; sheet.getRange("Y3:Y5").fillDown();
  sheet.getRange("AC3").formulas = [["=SUM(Z3:AB3)"]]; sheet.getRange("AC3:AC5").fillDown();
  sheet.getRange("AD3").formulas = [["=I3+Y3*1.5+AC3*0.75"]]; sheet.getRange("AD3:AD5").fillDown();
  editable(sheet, "A3:H5"); editable(sheet, "J3:X5"); editable(sheet, "Z3:AB5");
  sheet.getRange("I3:I5").format = { fill: light, font: { bold: true }, borders: { preset: "all", style: "thin", color: "#D9D9D9" } };
  sheet.getRange("Y3:Y5").format = { fill: light, font: { bold: true }, borders: { preset: "all", style: "thin", color: "#D9D9D9" } };
  sheet.getRange("AC3:AD5").format = { fill: light, font: { bold: true }, borders: { preset: "all", style: "thin", color: "#D9D9D9" } };
  sheet.freezePanes.freezeRows(2);
  workbook.recalculate();
  const check = await workbook.inspect({ kind: "table", range: "8月!A1:AD5", include: "values,formulas", tableMaxRows: 5, tableMaxCols: 30 });
  if (!check.ndjson.includes("教师甲")) throw new Error("续费推荐模板校验失败");
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(fileURLToPath(new URL("续费推荐数据模板.xlsx", outputDir)));
}

async function refundTemplate() {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("8月退费");
  sheet.showGridLines = false;
  const columns = [7, 12, 12, 14, 9, 11, 12, 11, 11, 13, 12, 12, 12, 12, 18, 13, 9, 11, 13, 9, 11, 13, 9, 11];
  columns.forEach((width, index) => { sheet.getCell(0, index).format.columnWidth = width; });
  title(sheet, "A1", "退费绩效确认模板");
  sheet.getRange("A2").values = [["同一笔退费如涉及多名教师，请继续向右填写下一组“教师 / 人头 / 绩效”。人头和绩效分别确认，同一学生的人头请避免重复计算。"]];
  sheet.getRange("A2").format = { font: { italic: true, color: "#5B6570" }, wrapText: true };
  sheet.getRange("A3:X4").values = [["周", "退费校区", "新签/续费", "学生", "年级", "消耗课时", "退费科目", "科目类型", "退费课时", "退费总金额", "是否为转校生", "班主任", "学科教师", "教育顾问", "备注", "退费绩效", null, null, "退费绩效", null, null, "退费绩效", null, null], ["周", "退费校区", "新签/续费", "学生", "年级", "消耗课时", "退费科目", "科目类型", "退费课时", "退费总金额", "是否为转校生", "班主任", "学科教师", "教育顾问", "备注", "教师", "人头", "绩效", "教师2", "人头2", "绩效2", "教师3", "人头3", "绩效3"]];
  header(sheet, "A3:X4");
  sheet.getRange("A5:X6").values = [[1, "示例校区", "续费", "学生甲", "高二", 0, "数学", "班课", 0, 0, "否", "班主任甲", "教师甲", "顾问甲", "示例：请按实际审核结果填写", "教师甲", 1, -100, "教师乙", 0, -50, null, null, null], [2, "示例校区", "新签", "学生乙", "初二", 0, "物理", "一对一", 0, 0, "否", "班主任乙", "教师丙", "顾问乙", "", "教师丙", 1, -80, null, null, null, null, null, null]];
  editable(sheet, "A5:X60");
  sheet.getRange("Q5:Q60").format.numberFormat = [["0"]];
  sheet.getRange("R5:R60").format.numberFormat = [["0.00"]];
  sheet.getRange("T5:T60").format.numberFormat = [["0"]];
  sheet.getRange("U5:U60").format.numberFormat = [["0.00"]];
  sheet.getRange("W5:W60").format.numberFormat = [["0"]];
  sheet.getRange("X5:X60").format.numberFormat = [["0.00"]];
  sheet.freezePanes.freezeRows(4);
  workbook.recalculate();
  const check = await workbook.inspect({ kind: "table", range: "8月退费!A1:X6", include: "values", tableMaxRows: 6, tableMaxCols: 24 });
  if (!check.ndjson.includes("教师2")) throw new Error("退费绩效模板校验失败");
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(fileURLToPath(new URL("退费绩效确认模板.xlsx", outputDir)));
}

await renewalTemplate();
await refundTemplate();
