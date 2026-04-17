# VPC y recursos de networking
# Arquitectura: 1 VPC con 2 public subnets (ALB) + 2 private subnets (ECS + RDS)

resource "aws_vpc" "axon" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.project_name}-${var.environment}-vpc"
  }
}

# Internet Gateway — acceso a internet desde public subnets
resource "aws_internet_gateway" "axon" {
  vpc_id = aws_vpc.axon.id

  tags = {
    Name = "${var.project_name}-${var.environment}-igw"
  }
}

# ============================================================================
# Public Subnets — para el ALB (accesible desde internet)
# ============================================================================

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.axon.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-${var.environment}-public-${count.index + 1}"
    Tier = "public"
  }
}

# ============================================================================
# Private Subnets — para ECS tasks y RDS (NO accesibles desde internet)
# ============================================================================

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.axon.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${var.project_name}-${var.environment}-private-${count.index + 1}"
    Tier = "private"
  }
}

# ============================================================================
# NAT Gateway — acceso outbound desde private subnets a internet
# ============================================================================

resource "aws_eip" "nat" {
  domain     = "vpc"
  depends_on = [aws_internet_gateway.axon]

  tags = {
    Name = "${var.project_name}-${var.environment}-nat-eip"
  }
}

resource "aws_nat_gateway" "axon" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.axon]

  tags = {
    Name = "${var.project_name}-${var.environment}-nat"
  }
}

# ============================================================================
# Route Tables — definir rutas para tráfico
# ============================================================================

# Route Table Pública — tráfico a internet va por IGW
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.axon.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.axon.id
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-rt-public"
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Route Table Privada — tráfico outbound va por NAT Gateway
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.axon.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.axon.id
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-rt-private"
  }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
