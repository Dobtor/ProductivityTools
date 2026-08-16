/** @odoo-module **/

/**
 * 內建心智圖範本（純資料 + 純建構函式）。
 *
 * 從 mindmap_editor.js 抽出來的原因很單純：這 300 多行完全沒有用到編輯器的
 * 任何狀態（原本 `this.` 只出現在呼叫 `_buildTemplate` 與取預設資料兩處），
 * 留在那個 7,000 行的 god-component 裡只是讓它更難讀。行為完全未變。
 *
 * `_t()` 在模組載入時求值 —— 與抽出前同樣是在 class 定義階段就被 Odoo 的
 * 延遲翻譯代理包住，語言切換仍然生效。
 */
import { _t } from "@web/core/l10n/translation";

/** 把「根主題 + 分支清單」攤成 render-engine 吃的 node_tree 結構。 */
function buildTemplate(rootTopic, branches) {
    const children = branches.map((branch, i) => {
        const childNodes = (branch.children || []).map((childTopic, j) => ({
            id: `node_t_${i}_${j}`,
            topic: childTopic,
            expanded: true,
            children: [],
            data: { style: { background: '#f8f9fa', color: '#333333' } },
        }));
        return {
            id: `node_b_${i}`,
            topic: branch.topic,
            expanded: true,
            children: childNodes,
            data: { style: branch.style || { background: '#e9ecef', color: '#333333' } },
        };
    });

    return {
        meta: { name: rootTopic, author: '', version: '1.0' },
        format: 'node_tree',
        data: {
            id: 'root',
            topic: rootTopic,
            expanded: true,
            children: children,
            data: { style: { background: '#428bca', color: '#ffffff', 'font-weight': 'bold', 'font-size': '18px' } },
        },
    };
}

/**
 * 範本清單。
 * @param {Object} defaultData 空白範本用的預設資料（由編輯器傳入，
 *   因為那份預設值跟畫布的初始狀態綁在一起）。
 */
export function getMindmapTemplates(defaultData) {
    return [
        {
            id: 'blank',
            name: _t('Blank Mind Map'),
            category: 'basic',
            icon: 'fa-file-o',
            data: defaultData,
        },
        {
            id: 'business_plan',
            name: _t('Business Plan'),
            category: 'business',
            icon: 'fa-briefcase',
            data: buildTemplate('Business Plan', [
                { topic: _t('Market Analysis'), children: [_t('Target Market'), _t('Competitors'), _t('Market Size')] },
                { topic: _t('Products & Services'), children: [_t('Core Product'), _t('Value Proposition'), _t('Pricing')] },
                { topic: _t('Marketing Strategy'), children: [_t('Channels'), _t('Campaigns'), _t('Budget')] },
                { topic: _t('Financial Plan'), children: [_t('Revenue Model'), _t('Cost Structure'), _t('Projections')] },
                { topic: _t('Team'), children: [_t('Key Roles'), _t('Hiring Plan'), _t('Advisors')] },
            ]),
        },
        {
            id: 'swot',
            name: _t('SWOT Analysis'),
            category: 'business',
            icon: 'fa-th-large',
            data: buildTemplate('SWOT Analysis', [
                { topic: _t('Strengths'), children: [_t('Strength 1'), _t('Strength 2'), _t('Strength 3')], style: { background: '#28a745', color: '#fff' } },
                { topic: _t('Weaknesses'), children: [_t('Weakness 1'), _t('Weakness 2'), _t('Weakness 3')], style: { background: '#dc3545', color: '#fff' } },
                { topic: _t('Opportunities'), children: [_t('Opportunity 1'), _t('Opportunity 2'), _t('Opportunity 3')], style: { background: '#007bff', color: '#fff' } },
                { topic: _t('Threats'), children: [_t('Threat 1'), _t('Threat 2'), _t('Threat 3')], style: { background: '#ffc107', color: '#333' } },
            ]),
        },
        {
            id: 'meeting',
            name: _t('Meeting Notes'),
            category: 'business',
            icon: 'fa-users',
            data: buildTemplate('Meeting Notes', [
                { topic: _t('Attendees'), children: [_t('Person 1'), _t('Person 2')] },
                { topic: _t('Agenda'), children: [_t('Item 1'), _t('Item 2'), _t('Item 3')] },
                { topic: _t('Discussion'), children: [_t('Point 1'), _t('Point 2')] },
                { topic: _t('Action Items'), children: [_t('Task 1'), _t('Task 2')] },
                { topic: _t('Next Meeting'), children: [_t('Date'), _t('Topics')] },
            ]),
        },
        {
            id: 'project',
            name: _t('Project Dashboard'),
            category: 'business',
            icon: 'fa-tasks',
            data: buildTemplate('Project Dashboard', [
                { topic: _t('Goals'), children: [_t('Goal 1'), _t('Goal 2')] },
                { topic: _t('Milestones'), children: [_t('Phase 1'), _t('Phase 2'), _t('Phase 3')] },
                { topic: _t('Resources'), children: [_t('Team'), _t('Budget'), _t('Tools')] },
                { topic: _t('Risks'), children: [_t('Risk 1'), _t('Risk 2')] },
                { topic: _t('Timeline'), children: [_t('Start'), _t('Checkpoints'), _t('Deadline')] },
            ]),
        },
        {
            id: 'cause_effect',
            name: _t('Cause & Effect (Fishbone)'),
            category: 'business',
            icon: 'fa-sitemap',
            data: buildTemplate('Problem Statement', [
                { topic: _t('People'), children: [_t('Training'), _t('Communication')] },
                { topic: _t('Process'), children: [_t('Workflow'), _t('Standards')] },
                { topic: _t('Technology'), children: [_t('Systems'), _t('Tools')] },
                { topic: _t('Environment'), children: [_t('Culture'), _t('Resources')] },
            ]),
        },
        {
            id: 'book_report',
            name: _t('Book Report'),
            category: 'education',
            icon: 'fa-book',
            data: buildTemplate('Book Title', [
                { topic: _t('Author'), children: [_t('Background'), _t('Other Works')] },
                { topic: _t('Characters'), children: [_t('Protagonist'), _t('Antagonist'), _t('Supporting')] },
                { topic: _t('Plot'), children: [_t('Beginning'), _t('Climax'), _t('Resolution')] },
                { topic: _t('Themes'), children: [_t('Theme 1'), _t('Theme 2')] },
                { topic: _t('My Opinion'), children: [_t('Liked'), _t('Disliked'), _t('Rating')] },
            ]),
        },
        {
            id: 'study_plan',
            name: _t('Study Plan'),
            category: 'education',
            icon: 'fa-graduation-cap',
            data: buildTemplate('Study Plan', [
                { topic: _t('Subjects'), children: [_t('Subject 1'), _t('Subject 2'), _t('Subject 3')] },
                { topic: _t('Schedule'), children: [_t('Morning'), _t('Afternoon'), _t('Evening')] },
                { topic: _t('Resources'), children: [_t('Textbooks'), _t('Online'), _t('Notes')] },
                { topic: _t('Goals'), children: [_t('Short-term'), _t('Long-term')] },
            ]),
        },
        {
            id: 'travel_plan',
            name: _t('Travel Plan'),
            category: 'personal',
            icon: 'fa-plane',
            data: buildTemplate('Travel Plan', [
                { topic: _t('Destination'), children: [_t('Places to Visit'), _t('Activities')] },
                { topic: _t('Logistics'), children: [_t('Flights'), _t('Hotels'), _t('Transport')] },
                { topic: _t('Budget'), children: [_t('Transportation'), _t('Accommodation'), _t('Food'), _t('Activities')] },
                { topic: _t('Packing'), children: [_t('Essentials'), _t('Clothing'), _t('Documents')] },
            ]),
        },
        {
            id: 'weekly_plan',
            name: _t('Weekly Plan'),
            category: 'personal',
            icon: 'fa-calendar',
            data: buildTemplate('This Week', [
                { topic: _t('Monday'), children: [_t('Task 1'), _t('Task 2')] },
                { topic: _t('Tuesday'), children: [_t('Task 1'), _t('Task 2')] },
                { topic: _t('Wednesday'), children: [_t('Task 1'), _t('Task 2')] },
                { topic: _t('Thursday'), children: [_t('Task 1'), _t('Task 2')] },
                { topic: _t('Friday'), children: [_t('Task 1'), _t('Task 2')] },
            ]),
        },
        {
            id: 'resume',
            name: _t('Resume / CV'),
            category: 'personal',
            icon: 'fa-id-card',
            data: buildTemplate('My Name', [
                { topic: _t('Contact Info'), children: [_t('Email'), _t('Phone'), _t('Location')] },
                { topic: _t('Experience'), children: [_t('Company 1'), _t('Company 2')] },
                { topic: _t('Education'), children: [_t('Degree 1'), _t('Degree 2')] },
                { topic: _t('Skills'), children: [_t('Technical'), _t('Soft Skills'), _t('Languages')] },
                { topic: _t('Projects'), children: [_t('Project 1'), _t('Project 2')] },
            ]),
        },
        // ===== Additional Business Templates =====
        {
            id: 'annual_report', name: _t('Annual Report'), category: 'business', icon: 'fa-bar-chart',
            data: buildTemplate('Annual Report 2024', [
                { topic: _t('Executive Summary'), children: [_t('Highlights'), _t('KPIs')] },
                { topic: _t('Financial Results'), children: [_t('Revenue'), _t('Expenses'), _t('Profit')] },
                { topic: _t('Operations'), children: [_t('Production'), _t('Quality'), _t('Efficiency')] },
                { topic: _t('Market Overview'), children: [_t('Market Share'), _t('Growth'), _t('Trends')] },
                { topic: _t('Outlook'), children: [_t('Goals'), _t('Investments'), _t('Risks')] },
            ]),
        },
        {
            id: 'balance_sheet', name: _t('Balance Sheet'), category: 'business', icon: 'fa-balance-scale',
            data: buildTemplate('Balance Sheet', [
                { topic: _t('Assets'), children: [_t('Current Assets'), _t('Fixed Assets'), _t('Intangible')] },
                { topic: _t('Liabilities'), children: [_t('Current'), _t('Long-term'), _t('Provisions')] },
                { topic: _t('Equity'), children: [_t('Share Capital'), _t('Retained Earnings')] },
            ]),
        },
        {
            id: 'business_timeline', name: _t('Business Timeline'), category: 'business', icon: 'fa-clock-o',
            data: buildTemplate('Company Timeline', [
                { topic: _t('Q1'), children: [_t('Jan'), _t('Feb'), _t('Mar')] },
                { topic: _t('Q2'), children: [_t('Apr'), _t('May'), _t('Jun')] },
                { topic: _t('Q3'), children: [_t('Jul'), _t('Aug'), _t('Sep')] },
                { topic: _t('Q4'), children: [_t('Oct'), _t('Nov'), _t('Dec')] },
            ]),
        },
        {
            id: 'company_hierarchy', name: _t('Company Hierarchy'), category: 'business', icon: 'fa-sitemap',
            data: buildTemplate('CEO', [
                { topic: _t('CTO'), children: [_t('Engineering'), _t('Product'), _t('QA')] },
                { topic: _t('CFO'), children: [_t('Accounting'), _t('Finance'), _t('Legal')] },
                { topic: _t('COO'), children: [_t('Operations'), _t('HR'), _t('Admin')] },
                { topic: _t('CMO'), children: [_t('Marketing'), _t('Sales'), _t('PR')] },
            ]),
        },
        {
            id: 'manufacturing_flow', name: _t('Manufacturing Flow'), category: 'business', icon: 'fa-industry',
            data: buildTemplate('Manufacturing Process', [
                { topic: _t('Raw Materials'), children: [_t('Sourcing'), _t('Inventory'), _t('Quality Check')] },
                { topic: _t('Production'), children: [_t('Assembly'), _t('Testing'), _t('Packaging')] },
                { topic: _t('Distribution'), children: [_t('Warehouse'), _t('Shipping'), _t('Delivery')] },
            ]),
        },
        {
            id: 'sales_mgmt', name: _t('Sales Management'), category: 'business', icon: 'fa-line-chart',
            data: buildTemplate('Sales Strategy', [
                { topic: _t('Pipeline'), children: [_t('Leads'), _t('Opportunities'), _t('Deals')] },
                { topic: _t('Channels'), children: [_t('Direct'), _t('Partners'), _t('Online')] },
                { topic: _t('Targets'), children: [_t('Monthly'), _t('Quarterly'), _t('Annual')] },
                { topic: _t('Team'), children: [_t('Reps'), _t('Managers'), _t('Training')] },
            ]),
        },
        {
            id: 'problem_solving', name: _t('Problem Solving'), category: 'business', icon: 'fa-puzzle-piece',
            data: buildTemplate('Problem Statement', [
                { topic: _t('Root Causes'), children: [_t('Cause 1'), _t('Cause 2'), _t('Cause 3')] },
                { topic: _t('Impact'), children: [_t('Cost'), _t('Time'), _t('Quality')] },
                { topic: _t('Solutions'), children: [_t('Option A'), _t('Option B'), _t('Option C')] },
                { topic: _t('Action Plan'), children: [_t('Step 1'), _t('Step 2'), _t('Step 3')] },
            ]),
        },
        // ===== Additional Education Templates =====
        {
            id: 'class_schedule', name: _t('Class Schedule'), category: 'education', icon: 'fa-calendar-check-o',
            data: buildTemplate('Class Schedule', [
                { topic: _t('Monday'), children: [_t('Math'), _t('Science'), _t('English')] },
                { topic: _t('Tuesday'), children: [_t('History'), _t('Art'), _t('PE')] },
                { topic: _t('Wednesday'), children: [_t('Math'), _t('Music'), _t('Science')] },
                { topic: _t('Thursday'), children: [_t('English'), _t('History'), _t('Lab')] },
                { topic: _t('Friday'), children: [_t('Math'), _t('Review'), _t('Club')] },
            ]),
        },
        {
            id: 'compare_contrast', name: _t('Compare & Contrast'), category: 'education', icon: 'fa-columns',
            data: buildTemplate('Comparison', [
                { topic: _t('Subject A'), children: [_t('Feature 1'), _t('Feature 2'), _t('Feature 3')], style: { background: '#007bff', color: '#fff' } },
                { topic: _t('Similarities'), children: [_t('Common 1'), _t('Common 2')] },
                { topic: _t('Subject B'), children: [_t('Feature 1'), _t('Feature 2'), _t('Feature 3')], style: { background: '#28a745', color: '#fff' } },
            ]),
        },
        {
            id: 'paper_outline', name: _t('Paper Outline'), category: 'education', icon: 'fa-file-text',
            data: buildTemplate('Paper Title', [
                { topic: _t('Introduction'), children: [_t('Hook'), _t('Background'), _t('Thesis')] },
                { topic: _t('Body'), children: [_t('Argument 1'), _t('Argument 2'), _t('Argument 3')] },
                { topic: _t('Counter-arguments'), children: [_t('Objection 1'), _t('Rebuttal')] },
                { topic: _t('Conclusion'), children: [_t('Summary'), _t('Implications'), _t('Call to Action')] },
                { topic: _t('References'), children: [_t('Source 1'), _t('Source 2')] },
            ]),
        },
        {
            id: 'exam_review', name: _t('Exam Review'), category: 'education', icon: 'fa-check-square',
            data: buildTemplate('Final Exam Review', [
                { topic: _t('Chapter 1'), children: [_t('Key Concepts'), _t('Formulas'), _t('Practice')] },
                { topic: _t('Chapter 2'), children: [_t('Key Concepts'), _t('Formulas'), _t('Practice')] },
                { topic: _t('Chapter 3'), children: [_t('Key Concepts'), _t('Formulas'), _t('Practice')] },
                { topic: _t('Study Tips'), children: [_t('Flash Cards'), _t('Group Study'), _t('Past Papers')] },
            ]),
        },
        {
            id: 'syllabus', name: _t('Syllabus'), category: 'education', icon: 'fa-graduation-cap',
            data: buildTemplate('Course Name', [
                { topic: _t('Instructor'), children: [_t('Name'), _t('Office Hours'), _t('Contact')] },
                { topic: _t('Schedule'), children: [_t('Week 1-4'), _t('Week 5-8'), _t('Week 9-12')] },
                { topic: _t('Grading'), children: [_t('Homework 30%'), _t('Midterm 30%'), _t('Final 40%')] },
                { topic: _t('Resources'), children: [_t('Textbook'), _t('Online'), _t('Library')] },
            ]),
        },
        // ===== Additional Personal Templates =====
        {
            id: 'diet_plan', name: _t('Diet Plan'), category: 'personal', icon: 'fa-cutlery',
            data: buildTemplate('Diet Plan', [
                { topic: _t('Breakfast'), children: [_t('Option 1'), _t('Option 2')] },
                { topic: _t('Lunch'), children: [_t('Option 1'), _t('Option 2')] },
                { topic: _t('Dinner'), children: [_t('Option 1'), _t('Option 2')] },
                { topic: _t('Snacks'), children: [_t('Healthy'), _t('Treats')] },
                { topic: _t('Goals'), children: [_t('Calories'), _t('Nutrition'), _t('Exercise')] },
            ]),
        },
        {
            id: 'party_prep', name: _t('Party Preparation'), category: 'personal', icon: 'fa-glass',
            data: buildTemplate('Party Plan', [
                { topic: _t('Guest List'), children: [_t('Friends'), _t('Family'), _t('Colleagues')] },
                { topic: _t('Venue'), children: [_t('Location'), _t('Decoration'), _t('Setup')] },
                { topic: _t('Food & Drinks'), children: [_t('Menu'), _t('Beverages'), _t('Desserts')] },
                { topic: _t('Entertainment'), children: [_t('Music'), _t('Games'), _t('Activities')] },
                { topic: _t('Budget'), children: [_t('Venue'), _t('Food'), _t('Other')] },
            ]),
        },
        {
            id: 'shopping_list', name: _t('Shopping List'), category: 'personal', icon: 'fa-shopping-cart',
            data: buildTemplate('Shopping List', [
                { topic: _t('Groceries'), children: [_t('Fruits'), _t('Vegetables'), _t('Dairy'), _t('Meat')] },
                { topic: _t('Household'), children: [_t('Cleaning'), _t('Kitchen'), _t('Bathroom')] },
                { topic: _t('Electronics'), children: [_t('Accessories'), _t('Cables')] },
                { topic: _t('Clothing'), children: [_t('Tops'), _t('Bottoms'), _t('Shoes')] },
            ]),
        },
    ];
}
