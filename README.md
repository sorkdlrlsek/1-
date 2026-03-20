# VPC Peering + ALB + NLB 인프라 구성 가이드

---

## 전체 아키텍처

```
                        ┌─────────────────────────────────────┐
                        │         APP VPC (10.0.0.0/16)       │
                        │                                     │
                        │  ┌──────────────────────────────┐   │
  [User]                │  │       Public Subnet          │   │
    │                   │  │                              │   │
    │  HTTP:80          │  │   [Bastion]      [ALB]       │   │
    └───────────────────┼──┼──────────────► (L7, :80)     │   │
                        │  └──────────────────┬───────────┘   │
                        │                     │ HTTP:8080     │
                        │  ┌──────────────────▼───────────┐   │
                        │  │       Private Subnet         │   │
                        │  │                              │   │
                        │  │        [App Server EC2]      │   │
                        │  └──────────────────┬───────────┘   │
                        └─────────────────────┼───────────────┘
                                              │
                                    VPC Peering 연결
                                              │
                        ┌─────────────────────▼───────────────┐
                        │         DB VPC (10.1.0.0/16)        │
                        │                                     │
                        │  ┌──────────────────────────────┐   │
                        │  │       Private Subnet         │   │
                        │  │                              │   │
                        │  │   [NLB] ──TCP:3307──► [RDS]  │   │
                        │  │   (L4)                MySQL  │   │
                        │  └──────────────────────────────┘   │
                        └─────────────────────────────────────┘

                   [Secrets Manager]  [KMS]  [CloudWatch]
                    (DB 접속 정보)   (암호화)  (로그/메트릭)
```

---

## Task 1 - VPC 및 서브넷 구성

### 1-1. App VPC

> 애플리케이션 서버와 ALB가 위치하는 VPC

| 항목 | 값 |
|---|---|
| VPC 이름 | `worldpay-app-vpc` |
| CIDR | `10.0.0.0/16` |
| 인터넷 게이트웨이 | `worldpay-app-igw` |
| NAT 게이트웨이 | `worldpay-app-nat` (Public Subnet-a에 배치) |

**서브넷 구성**

| 서브넷 이름 | CIDR | 가용 영역 | 유형 | 용도 |
|---|---|---|---|---|
| `worldpay-app-public-subnet-a` | `10.0.1.0/24` | ap-northeast-2a | Public | Bastion, ALB |
| `worldpay-app-public-subnet-c` | `10.0.2.0/24` | ap-northeast-2c | Public | ALB (이중화) |
| `worldpay-app-private-subnet-a` | `10.0.3.0/24` | ap-northeast-2a | Private | App Server |
| `worldpay-app-private-subnet-c` | `10.0.4.0/24` | ap-northeast-2c | Private | App Server (이중화) |

**라우팅 테이블**

| 라우팅 테이블 | 대상 | 타겟 | 설명 |
|---|---|---|---|
| `worldpay-app-igw` (Public RT) | `0.0.0.0/0` | IGW | 인터넷 트래픽 |
| `worldpay-app-igw` (Public RT) | `10.1.0.0/16` | Peering | DB VPC 통신 |
| `worldpay-app-nat-a` (Private RT) | `0.0.0.0/0` | NAT | 아웃바운드 인터넷 |
| `worldpay-app-nat-a` (Private RT) | `10.1.0.0/16` | Peering | DB VPC 통신 |
| `worldpay-app-nat-b` (Private RT) | `0.0.0.0/0` | NAT | 아웃바운드 인터넷 |
| `worldpay-app-nat-b` (Private RT) | `10.1.0.0/16` | Peering | DB VPC 통신 |

---

### 1-2. DB VPC

> RDS와 NLB가 위치하는 VPC (외부 인터넷과 완전 차단)

| 항목 | 값 |
|---|---|
| VPC 이름 | `worldpay-db-vpc` |
| CIDR | `10.1.0.0/16` |
| 인터넷 게이트웨이 | 없음 (완전 Private) |

**서브넷 구성**

| 서브넷 이름 | CIDR | 가용 영역 | 유형 | 용도 |
|---|---|---|---|---|
| `worldpay-db-private-subnet-a` | `10.1.1.0/24` | ap-northeast-2a | Private | RDS, NLB |
| `worldpay-db-private-subnet-c` | `10.1.2.0/24` | ap-northeast-2c | Private | RDS (다중 AZ 대기) |

**라우팅 테이블**

| 라우팅 테이블 | 대상 | 타겟 | 설명 |
|---|---|---|---|
| `worldpay-db-rtb` | `10.1.0.0/16` | local | DB VPC 내부 통신 |
| `worldpay-db-rtb` | `10.0.0.0/16` | Peering | App VPC 통신 |

---

## Task 2 - VPC Peering 구성

> App VPC ↔ DB VPC 간 프라이빗 네트워크 연결

| 항목 | 값 |
|---|---|
| Peering 이름 | `worldpay-peering` |
| 요청자 (Requester) | `worldpay-app-vpc` |
| 수락자 (Accepter) | `worldpay-db-vpc` |

**구성 순서**

1. App VPC에서 Peering 요청 생성
2. DB VPC 측에서 **수락(Accept)** 클릭
3. 양쪽 VPC 라우팅 테이블에 상대방 CIDR 경로 추가 (위 Task 1 라우팅 표 참고)

---

## Task 3 - Bastion 서버 구성

> Private 서브넷 리소스(App Server, RDS)에 접근하기 위한 점프 서버

| 항목 | 값 |
|---|---|
| 위치 | App VPC, Public 서브넷 |
| 목적 | SSH 터널링을 통한 App Server 및 RDS 접근 |

**보안 그룹**

| 방향 | 프로토콜 | 포트 | 소스/대상 | 목적 |
|---|---|---|---|---|
| 인바운드 | SSH (TCP) | 22 | `0.0.0.0/0` | 외부에서 Bastion 접속 |
| 아웃바운드 | SSH (TCP) | 22 | `0.0.0.0/0` | App Server SSH 접근 |
| 아웃바운드 | TCP | 3307 | `10.1.0.0/16` | RDS 직접 접근 (DB 관리용) |
| 아웃바운드 | HTTP (TCP) | 80 | `0.0.0.0/0` | 패키지 설치 등 |
| 아웃바운드 | HTTPS (TCP) | 443 | `0.0.0.0/0` | 패키지 설치 등 |

**RDS 접속 예시 (Bastion에서)**

```bash
mysql -h worldpay-rds.cmj5m2fzc8ae.ap-northeast-2.rds.amazonaws.com \
      -P 3307 \
      -u admin \
      -p
```

---

## Task 4 - RDS 구성

> DB VPC Private 서브넷에 배치되는 MySQL 데이터베이스

| 항목 | 값 |
|---|---|
| 엔진 | MySQL |
| 배포 옵션 | 다중 AZ DB 인스턴스 배포 (Primary 1개 + Standby 1개) |
| VPC | `worldpay-db-vpc` |
| 포트 | `3307` (기본 3306에서 변경) |
| 퍼블릭 액세스 | **비활성화** |
| 보안 그룹 | `rds-sg` |
| 암호화 | AWS KMS (`rds-kms-key`) |
| 자격 증명 관리 | AWS Secrets Manager |

**RDS 보안 그룹 (`rds-sg`) 인바운드 규칙**

| 프로토콜 | 포트 | 소스 | 허용 대상 |
|---|---|---|---|
| TCP | 3307 | `10.0.0.0/16` | Bastion, App Server (App VPC 전체) |
| TCP | 3307 | `10.1.0.0/16` | NLB (DB VPC 내부) |

**CloudWatch 로그 내보내기**

| 로그 유형 | 활성화 |
|---|---|
| 감사 로그 | ✅ |
| 에러 로그 | ✅ |
| 일반 로그 | ✅ |
| IAM DB 인증 에러 로그 | ✅ |
| 느린 쿼리 로그 | ✅ |

**초기 데이터베이스 및 테이블 생성**

```sql
CREATE DATABASE worldpay;

USE worldpay;

CREATE TABLE user (
    id    VARCHAR(255),
    name  VARCHAR(255),
    gmdsi VARCHAR(255)
);
```

---

## Task 5 - App Server (EC2) 구성

> ALB로부터 트래픽을 받아 비즈니스 로직을 처리하는 애플리케이션 서버

| 항목 | 값 |
|---|---|
| 위치 | App VPC, Private 서브넷 |
| 애플리케이션 포트 | `8080` |

**보안 그룹 인바운드 규칙**

| 프로토콜 | 포트 | 소스 | 목적 |
|---|---|---|---|
| TCP | 8080 | `0.0.0.0/0` | ALB 헬스체크 및 트래픽 수신 |
| SSH (TCP) | 22 | `0.0.0.0/0` | Bastion을 통한 SSH 접근 |

---

## Task 6 - ALB (Application Load Balancer) 구성

> 외부 사용자의 HTTP 요청을 받아 App Server로 분산하는 L7 로드 밸런서

| 항목 | 값 |
|---|---|
| 유형 | Application Load Balancer (L7) |
| 체계 | 인터넷 경계 (Internet-facing) |
| VPC | `worldpay-app-vpc` |
| 서브넷 | `worldpay-app-public-subnet-a`, `worldpay-app-public-subnet-c` |
| 보안 그룹 | `alb-sg` |
| 리스너 | HTTP:80 |

**ALB 보안 그룹 (`alb-sg`) 인바운드 규칙**

| 프로토콜 | 포트 | 소스 | 목적 |
|---|---|---|---|
| HTTP (TCP) | 80 | `0.0.0.0/0` | 외부 사용자 HTTP 접근 |

**대상 그룹 (`worldpay-tg`) 설정**

| 항목 | 값 |
|---|---|
| 대상 유형 | 인스턴스 (Instance) |
| 프로토콜 | HTTP |
| 포트 | 8080 |
| VPC | `worldpay-app-vpc` |
| 헬스체크 프로토콜 | HTTP |

**리스너 규칙**

```
HTTP:80 → 대상 그룹(worldpay-tg)으로 전달
```

---

## Task 7 - NLB (Network Load Balancer) 구성

> App Server에서 오는 DB 트래픽을 RDS로 전달하는 L4 로드 밸런서
> (App VPC → DB VPC 간 VPC Peering을 통해 통신)

| 항목 | 값 |
|---|---|
| 유형 | Network Load Balancer (L4) |
| 체계 | 내부 (Internal) |
| VPC | `worldpay-db-vpc` |
| 서브넷 | `worldpay-db-private-subnet-a`, `worldpay-db-private-subnet-c` |
| 보안 그룹 | `nlb-sg` |
| 리스너 | TCP:3307 |

**NLB 보안 그룹 (`nlb-sg`) 인바운드 규칙**

| 프로토콜 | 포트 | 소스 | 목적 |
|---|---|---|---|
| TCP | 3307 | `10.0.0.0/16` | App VPC(App Server)에서의 DB 트래픽 |

**대상 그룹 (`worldpay-nlb-tg`) 설정**

| 항목 | 값 |
|---|---|
| 대상 유형 | IP 주소 (VPC Peering 대상이므로 IP 타입 필수) |
| 프로토콜 | TCP |
| 포트 | 3307 |
| VPC | `worldpay-db-vpc` |
| 헬스체크 프로토콜 | TCP |

**RDS IP 주소 확인 및 등록 방법**

```bash
# Bastion 또는 App Server에서 RDS 엔드포인트의 IP 확인
nslookup worldpay-rds.cmj5m2fzc8ae.ap-northeast-2.rds.amazonaws.com

# 출력 예시
# Address: 10.1.146.235  ← 이 IP를 대상 그룹에 등록
```

> ⚠️ RDS의 IP는 재시작 시 변경될 수 있으므로, 변경 시 대상 그룹 IP를 업데이트해야 합니다.

**리스너 규칙**

```
TCP:3307 → 대상 그룹(worldpay-nlb-tg)으로 전달
```

---

## 전체 트래픽 흐름 정리

```
① 외부 사용자가 ALB DNS로 HTTP:80 요청
        ↓
② ALB가 L7에서 요청을 수신 → App Server EC2로 HTTP:8080 전달
        ↓
③ App Server가 비즈니스 로직 처리 후 DB 조회 필요 시
   → VPC Peering을 통해 DB VPC의 NLB(TCP:3307)로 요청
        ↓
④ NLB가 L4에서 TCP 트래픽 수신 → RDS MySQL(TCP:3307)로 전달
        ↓
⑤ RDS에서 데이터 처리 후 결과 반환
```

---

## 부가 서비스

| 서비스 | 역할 | 연결 대상 |
|---|---|---|
| **AWS Secrets Manager** | RDS 마스터 사용자 자격 증명(ID/PW) 자동 관리 및 순환 | RDS |
| **AWS KMS** | RDS 저장 데이터 암호화 (`rds-kms-key` 사용) | RDS |
| **Amazon CloudWatch** | RDS 로그(감사/에러/쿼리 등) 및 메트릭 수집·모니터링 | RDS |
