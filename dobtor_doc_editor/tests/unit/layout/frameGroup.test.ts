/**
 * Sprint 169：frameGroup —— `<w:framePr>` 框段落偵測與分組（純函式）
 *
 * 涵蓋：
 *   - isFramedParagraph：段落有 / 無 framePr、非段落
 *   - framePrEqual：相等 / 不等 / undefined 邊界
 *   - frameGroupLength：單段 / 連續同 framePr / 不同 framePr 斷組 / 非框段落斷組
 */

import { describe, expect, it } from 'vitest';
import { isFramedParagraph, framePrEqual, frameGroupLength } from '../../../static/src/core/layout/frameGroup';
import type { ParagraphNode, ParagraphProps, TableNode } from '../../../static/src/core/ooxml/ast/types';

type FramePr = NonNullable<ParagraphProps['framePr']>;

function framedPara(framePr?: FramePr): ParagraphNode {
  const props: ParagraphProps = {};
  if (framePr) props.framePr = framePr;
  return { type: 'paragraph', props, runs: [{ type: 'run', text: 'x', props: {} }] };
}

const FP_A: FramePr = { wrap: 'around', vAnchor: 'text', hAnchor: 'margin', y: 8.3 };
const FP_B: FramePr = { wrap: 'around', vAnchor: 'text', hAnchor: 'margin', y: 16 };

describe('frameGroup — isFramedParagraph', () => {
  it('段落有 framePr → true', () => {
    expect(isFramedParagraph(framedPara(FP_A))).toBe(true);
  });

  it('段落無 framePr → false', () => {
    expect(isFramedParagraph(framedPara())).toBe(false);
  });

  it('非段落（table）→ false', () => {
    const tbl = { type: 'table', rows: [], props: {} } as unknown as TableNode;
    expect(isFramedParagraph(tbl)).toBe(false);
  });
});

describe('frameGroup — framePrEqual', () => {
  it('同一物件 → true', () => {
    expect(framePrEqual(FP_A, FP_A)).toBe(true);
  });

  it('結構相等的不同物件 → true', () => {
    expect(framePrEqual({ ...FP_A }, { ...FP_A })).toBe(true);
  });

  it('欄位不同 → false', () => {
    expect(framePrEqual(FP_A, FP_B)).toBe(false);
  });

  it('兩者皆 undefined → true', () => {
    expect(framePrEqual(undefined, undefined)).toBe(true);
  });

  it('單邊 undefined → false', () => {
    expect(framePrEqual(FP_A, undefined)).toBe(false);
    expect(framePrEqual(undefined, FP_A)).toBe(false);
  });
});

describe('frameGroup — frameGroupLength', () => {
  it('單一框段落 → 1', () => {
    const body = [framedPara(FP_A), framedPara()];
    expect(frameGroupLength(body, 0)).toBe(1);
  });

  it('連續同 framePr 框段落 → N', () => {
    const body = [framedPara(FP_A), framedPara({ ...FP_A }), framedPara({ ...FP_A }), framedPara()];
    expect(frameGroupLength(body, 0)).toBe(3);
  });

  it('遇到不同 framePr 斷組', () => {
    const body = [framedPara(FP_A), framedPara(FP_B)];
    expect(frameGroupLength(body, 0)).toBe(1);
  });

  it('遇到非框段落斷組', () => {
    const body = [framedPara(FP_A), framedPara(), framedPara(FP_A)];
    expect(frameGroupLength(body, 0)).toBe(1);
  });

  it('startIdx 非框段落 → 0', () => {
    const body = [framedPara(), framedPara(FP_A)];
    expect(frameGroupLength(body, 0)).toBe(0);
  });

  it('group 延伸到 body 結尾', () => {
    const body = [framedPara(FP_A), framedPara({ ...FP_A })];
    expect(frameGroupLength(body, 0)).toBe(2);
  });
});
