# Application Load Balancer
# Público en public subnets, rutea tráfico HTTP a ECS tasks en puerto 8420

resource "aws_lb" "axon" {
  name               = "${var.project_name}-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection = var.environment == "prod"
  enable_http2               = true
  enable_cross_zone_load_balancing = true

  tags = {
    Name = "${var.project_name}-${var.environment}-alb"
  }
}

# Target Group — apunta a los ECS tasks en puerto 8420
resource "aws_lb_target_group" "axon" {
  name        = "${var.project_name}-${var.environment}-tg"
  port        = 8420
  protocol    = "HTTP"
  vpc_id      = aws_vpc.axon.id
  target_type = "ip"

  health_check {
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    path                = "/v1/health/live"
    matcher             = "200"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-target-group"
  }
}

# Listener — HTTP en puerto 80, forward a target group
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.axon.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.axon.arn
  }
}
