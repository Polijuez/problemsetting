import Data.List (sort)
import System.Environment (getArgs)
import Text.Printf (printf)

main :: IO ()
main = do
  args <- getArgs
  case args of
    (infile : outfile : _) -> do
      contents <- readFile infile
      writeFile outfile (solve contents)
    _ -> interact solve

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
