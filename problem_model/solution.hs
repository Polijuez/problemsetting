import Data.List (sort)
import Text.Printf (printf)

main :: IO ()
main = interact solve

solve :: String -> String
solve contents =
  let (n : rest) = map read (words contents) :: [Int]
      xs = take n rest
   in printf "%.1f\n" (median xs)

median :: [Int] -> Float
median xs =
  let ys = sort xs
      n = length ys
      mid = n `div` 2
   in if odd n
        then fromIntegral (ys !! mid)
        else fromIntegral (ys !! (mid - 1) + ys !! mid) / 2
