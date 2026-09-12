# NOTICE — 자료에 관한 고지

[`LICENSE`](LICENSE)(MIT)는 **이 저장소의 코드와 문서에만** 적용된다.
아래 원자료는 그 대상이 아니며 각 제공기관의 조건을 따른다.

## 원자료

| 자료 | 제공 | 조건 |
|---|---|---|
| 연도별 HSK 10단위 관세율표·주요세율보기 화면(2007~2026) | 관세청 관세법령정보포털(CLIP) | 같은 자료의 공공데이터포털 공개본 「품목번호별 관세율표」(15051179)가 공공누리 제1유형 — **출처표시 의무**. 화면 자체에는 공공누리 표시가 없다 |
| 관세법·FTA 관세특례법·양허관세 규정 조문 | 국가법령정보센터 | 공공저작물 |

**공공누리 제1유형은 출처표시가 의무이고, 빠뜨리면 이용허락이 자동으로 종료된다.**
자료의 출처와 URL은 README의 「출처와 이용 조건」 절과 대시보드의 「받기·사용」 탭에 있다.
**재배포할 때 그 절을 그대로 유지해야 한다.**

관세청이 이 DB를 후원하거나 특수 관계에 있는 것으로 오인하게 하는 표시를 해서는 안 된다.

## 배포되는 DB 파일

DB 실물(`kcstariff.duckdb`)은 이 저장소에 없고 GitHub Releases로 배포된다.
그 파일도 이 라이선스의 대상이 아니며, 위 원자료의 조건을 그대로 따른다.

## 우리가 계산한 것과 법적 효력

`fct_applied_rate`(실행세율)와 `dim_origin_regime`(원산지→협정)은 **관세청이 공표한 값이 아니다.**
이 저장소가 관세법 제50조·FTA 관세특례법 제5조·양허관세 규정 제6조를 해석해 계산한 파생값이며,
판단이 필요했던 곳(조정관세의 순위, 세율이 하나로 정해지지 않는 코드)은 대시보드의 「실행세율」 탭에 적혀 있다.

관세법령정보포털은 10단위 세율이 참고용이며 법적 효력이 없다고 밝힌다.
**세액 계산이나 수입신고에는 관세법 별표와 해당 규정의 원문을 확인해야 하며, 재배포하거나 인용할 때는 파생값임을 함께 밝힌다.**

---

This NOTICE accompanies the MIT licence in `LICENSE`, which covers the source code and
documentation only. The underlying tariff data remains subject to the terms of its
provider, the Korea Customs Service; the same data as published on the Korean open data
portal is released under the Korea Open Government License Type 1, which makes attribution
mandatory. The applicable-rate table is this repository's own derivation from the statutory
priority rules, not an official determination, and the portal states that 10-digit rates
are for reference only and carry no legal effect.
